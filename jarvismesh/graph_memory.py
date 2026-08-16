"""
Module de Graphe de Connaissances (GraphRAG / Knowledge Graph) pour JarvisMesh.

Stocke et interroge des relations sémantiques structurées (sujet, prédicat, objet)
dans SQLite pour permettre le raisonnement multi-sauts et l'extraction relationnelle.
"""
from __future__ import annotations
import collections
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, List, Optional


class KnowledgeGraphStore:
    """Base de données de graphe de connaissances stockée dans SQLite."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    entity_type TEXT,
                    attributes TEXT,
                    updated_at REAL
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS triples (
                    id TEXT PRIMARY KEY,
                    subject TEXT NOT NULL,
                    predicate TEXT NOT NULL,
                    object TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    metadata TEXT,
                    created_at REAL
                )
            """)
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_triples_sub ON triples(subject)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_triples_obj ON triples(object)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_triples_pred ON triples(predicate)")

    def add_entity(self, name: str, entity_type: str = "concept", attributes: Optional[dict] = None) -> str:
        """Enregistre ou met à jour une entité."""
        uid = hashlib.sha256(name.lower().encode("utf-8")).hexdigest()[:16]
        meta = json.dumps(attributes or {})
        now = time.time()
        with self.conn:
            self.conn.execute(
                "INSERT INTO entities (id, name, entity_type, attributes, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(name) DO UPDATE SET entity_type=excluded.entity_type, attributes=excluded.attributes, updated_at=excluded.updated_at",
                (uid, name, entity_type, meta, now)
            )
        return uid

    def add_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float = 1.0,
        metadata: Optional[dict] = None,
    ) -> str:
        """Enregistre une relation sémantique (sujet, prédicat, objet)."""
        # Enregistre implicitement les entités
        self.add_entity(subject)
        self.add_entity(object_)

        raw_id = f"{subject.lower()}:{predicate.lower()}:{object_.lower()}"
        uid = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()[:16]
        meta = json.dumps(metadata or {})
        now = time.time()

        with self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO triples (id, subject, predicate, object, confidence, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uid, subject, predicate, object_, confidence, meta, now)
            )
        return uid

    def query_relations(self, entity: str, direction: str = "both") -> list[dict[str, Any]]:
        """Recherche les triplets connectés à une entité donnée."""
        cursor = self.conn.cursor()
        results = []

        if direction in ("out", "both"):
            cursor.execute("SELECT id, subject, predicate, object, confidence, metadata FROM triples WHERE LOWER(subject) = LOWER(?)", (entity,))
            for r in cursor.fetchall():
                results.append({
                    "id": r[0],
                    "subject": r[1],
                    "predicate": r[2],
                    "object": r[3],
                    "confidence": r[4],
                    "direction": "out",
                })

        if direction in ("in", "both"):
            cursor.execute("SELECT id, subject, predicate, object, confidence, metadata FROM triples WHERE LOWER(object) = LOWER(?)", (entity,))
            for r in cursor.fetchall():
                results.append({
                    "id": r[0],
                    "subject": r[1],
                    "predicate": r[2],
                    "object": r[3],
                    "confidence": r[4],
                    "direction": "in",
                })

        return results

    def find_path(self, start_entity: str, end_entity: str, max_depth: int = 3) -> list[list[dict[str, Any]]]:
        """Recherche les chemins relationnels les plus courts entre 2 entités (BFS)."""
        queue = collections.deque([[start_entity]])
        visited = {start_entity.lower()}
        valid_paths = []

        while queue:
            path = queue.popleft()
            curr = path[-1]

            if curr.lower() == end_entity.lower() and len(path) > 1:
                valid_paths.append(path)
                continue

            if len(path) > max_depth:
                continue

            relations = self.query_relations(curr, direction="out")
            for rel in relations:
                neighbor = rel["object"]
                if neighbor.lower() not in visited:
                    visited.add(neighbor.lower())
                    queue.append(path + [neighbor])

        return valid_paths

    def count(self) -> dict[str, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM entities")
        n_entities = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM triples")
        n_triples = cursor.fetchone()[0]
        return {"entities": n_entities, "triples": n_triples}

    def close(self):
        self.conn.close()


def get_graph_skills(graph: Optional[KnowledgeGraphStore] = None) -> dict[str, Callable]:
    """Compétences mesh pour interagir avec le graphe de connaissances."""
    store = graph or KnowledgeGraphStore()

    async def graph_store_triple(payload: dict) -> dict:
        sub = payload.get("subject")
        pred = payload.get("predicate")
        obj = payload.get("object")
        if not sub or not pred or not obj:
            return {"ok": False, "error": "Champs 'subject', 'predicate' et 'object' requis."}
        tid = store.add_triple(sub, pred, obj, confidence=float(payload.get("confidence", 1.0)))
        return {"ok": True, "triple_id": tid, "stored": True}

    async def graph_query_relations(payload: dict) -> dict:
        entity = payload.get("entity", "")
        direction = payload.get("direction", "both")
        relations = store.query_relations(entity, direction=direction)
        return {"ok": True, "relations": relations, "count": len(relations)}

    async def graph_find_path(payload: dict) -> dict:
        start_e = payload.get("start")
        end_e = payload.get("end")
        paths = store.find_path(start_e, end_e, max_depth=int(payload.get("max_depth", 3)))
        return {"ok": True, "paths": paths, "count": len(paths)}

    return {
        "graph_store_triple": graph_store_triple,
        "graph_query_relations": graph_query_relations,
        "graph_find_path": graph_find_path,
    }
