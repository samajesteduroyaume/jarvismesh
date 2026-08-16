"""
Module de Mémoire Persistante SQLite et Embeddings Vectoriels pour JarvisMesh.

Permet aux agents du maillage de stocker et rappeler des connaissances,
des documents et des souvenirs de conversation (mémoire épisodique et sémantique)
dans une base SQLite persistante et performante.
"""
from __future__ import annotations
import array
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple


class DenseEmbeddingEngine:
    """Générateur d'embeddings vectoriels denses normalisés.
    
    Utilise une projection sémantique multi-échelle par n-grammes de sous-mots
    produisant des vecteurs de dimension fixe (par défaut 128D) avec distance cosinus.
    """

    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        """Génère un vecteur dense normalisé (norme L2 = 1.0) pour un texte donné."""
        if not text:
            return [0.0] * self.dimension

        cleaned = text.lower().strip()
        words = re.findall(r"\b\w+\b", cleaned)
        if not words:
            return [0.0] * self.dimension

        vector = [0.0] * self.dimension

        # Feature hashing sur les mots complets et n-grammes de caractères (3 et 4)
        tokens = list(words)
        for w in words:
            if len(w) >= 3:
                w_padded = f"_{w}_"
                for n in (3, 4):
                    for i in range(len(w_padded) - n + 1):
                        tokens.append(w_padded[i : i + n])

        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest()[:8], 16)
            idx = h % self.dimension
            vector[idx] += 1.0

        # Normalisation L2
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0.0:
            vector = [v / norm for v in vector]
        return vector

    def batch_embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Calcule la similarité cosinus entre 2 vecteurs normalisés."""
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    return max(0.0, min(1.0, sum(a * b for a, b in zip(vec_a, vec_b))))


def _vec_to_blob(vec: list[float]) -> bytes:
    """Sérialise un vecteur float en BLOB binaire compact."""
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_vec(blob: bytes) -> list[float]:
    """Désérialise un BLOB binaire en liste de floats."""
    count = len(blob) // 4
    return list(struct.unpack(f"{count}f", blob))


class SQLiteVectorStore:
    """Base de données vectorielle SQLite persistante pour documents et mémoires."""

    def __init__(self, db_path: str | Path = ":memory:", embedding_engine: Optional[DenseEmbeddingEngine] = None):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.engine = embedding_engine or DenseEmbeddingEngine()
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    text TEXT NOT NULL,
                    metadata TEXT,
                    embedding BLOB,
                    created_at REAL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding BLOB,
                    timestamp REAL
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_session ON episodes(session_id)")

    def add_document(self, text: str, doc_id: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        """Stocke un document et son embedding dense dans SQLite."""
        uid = doc_id or hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
        meta_json = json.dumps(metadata or {})
        vec = self.engine.embed(text)
        blob = _vec_to_blob(vec)
        now = time.time()

        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO documents (id, text, metadata, embedding, created_at) VALUES (?, ?, ?, ?, ?)",
                (uid, text, meta_json, blob, now)
            )
        return uid

    def search(self, query: str, top_k: int = 5, min_score: float = 0.0) -> list[dict[str, Any]]:
        """Recherche sémantique par similarité cosinus sur les documents stockés."""
        query_vec = self.engine.embed(query)
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, text, metadata, embedding, created_at FROM documents")
        rows = cursor.fetchall()

        results = []
        for doc_id, text, meta_str, blob, created_at in rows:
            if not blob:
                continue
            doc_vec = _blob_to_vec(blob)
            score = _cosine_similarity(query_vec, doc_vec)
            if score >= min_score:
                try:
                    meta = json.loads(meta_str)
                except Exception:
                    meta = {}
                results.append({
                    "id": doc_id,
                    "text": text,
                    "metadata": meta,
                    "score": round(score, 4),
                    "created_at": created_at,
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def count(self) -> int:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM documents")
        return cursor.fetchone()[0]

    def close(self):
        self.conn.close()


class ConversationMemory:
    """Gestionnaire de mémoire épisodique et conversationnelle persistante."""

    def __init__(self, vector_store: SQLiteVectorStore):
        self.store = vector_store

    def add_turn(self, session_id: str, role: str, content: str, turn_id: Optional[str] = None) -> str:
        """Enregistre un tour de conversation avec embedding sémantique."""
        uid = turn_id or f"{session_id}_{int(time.time() * 1000)}_{role}"
        vec = self.store.engine.embed(content)
        blob = _vec_to_blob(vec)
        now = time.time()

        with self.store.conn:
            self.store.conn.execute(
                "INSERT OR REPLACE INTO episodes (id, session_id, role, content, embedding, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (uid, session_id, role, content, blob, now)
            )
        return uid

    def recall(self, query: str, session_id: Optional[str] = None, top_k: int = 4) -> list[dict[str, Any]]:
        """Rappelle les souvenirs et tours de conversations passés les plus pertinents."""
        query_vec = self.store.engine.embed(query)
        cursor = self.store.conn.cursor()
        
        if session_id:
            cursor.execute(
                "SELECT id, session_id, role, content, embedding, timestamp FROM episodes WHERE session_id = ?",
                (session_id,)
            )
        else:
            cursor.execute("SELECT id, session_id, role, content, embedding, timestamp FROM episodes")
            
        rows = cursor.fetchall()
        scored = []
        for uid, sess, role, content, blob, ts in rows:
            if not blob:
                continue
            vec = _blob_to_vec(blob)
            score = _cosine_similarity(query_vec, vec)
            scored.append({
                "id": uid,
                "session_id": sess,
                "role": role,
                "content": content,
                "score": round(score, 4),
                "timestamp": ts,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_history(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """Récupère l'historique chronologique d'une session."""
        cursor = self.store.conn.cursor()
        cursor.execute(
            "SELECT id, session_id, role, content, timestamp FROM episodes WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            (session_id, limit)
        )
        rows = cursor.fetchall()
        return [{"id": r[0], "session_id": r[1], "role": r[2], "content": r[3], "timestamp": r[4]} for r in rows]


class MemorySkillsManager:
    """Générateur de compétences mesh pour exposer la mémoire SQLite partagée."""

    def __init__(self, memory: ConversationMemory):
        self.memory = memory

    def get_skills(self) -> dict[str, Callable]:
        async def memory_store(payload: dict) -> dict:
            text = payload.get("text") or payload.get("content", "")
            session_id = payload.get("session_id", "default")
            role = payload.get("role", "agent")
            if not text:
                return {"ok": False, "error": "Le champ 'text' est requis"}
            turn_id = self.memory.add_turn(session_id, role, text)
            return {"ok": True, "turn_id": turn_id, "stored": True}

        async def memory_recall(payload: dict) -> dict:
            query = payload.get("query", "")
            session_id = payload.get("session_id")
            top_k = int(payload.get("top_k", 4))
            results = self.memory.recall(query, session_id=session_id, top_k=top_k)
            return {"ok": True, "memories": results, "count": len(results)}

        async def memory_search(payload: dict) -> dict:
            query = payload.get("query", "")
            top_k = int(payload.get("top_k", 5))
            results = self.memory.store.search(query, top_k=top_k)
            return {"ok": True, "results": results, "count": len(results)}

        return {
            "memory_store": memory_store,
            "memory_recall": memory_recall,
            "memory_search": memory_search,
        }
