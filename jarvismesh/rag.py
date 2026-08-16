"""
Mémoire partagée et RAG local distribué (Retrieval-Augmented Generation) pour JarvisMesh.

Fournit une base vectorielle embarquée légère, un moteur de recherche sémantique
par similarité cosinus et les compétences 'rag_index', 'rag_search' et 'rag_ask'.
"""
from __future__ import annotations
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Callable, Optional


def _tokenize(text: str) -> list[str]:
    """Tokenisation basique insensible à la casse et ponctuation."""
    return re.findall(r"\b\w{2,}\b", text.lower())


class LocalVectorStore:
    """Base de données vectorielle locale avec indexation et recherche par similarité cosinus."""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path).resolve() if db_path else None
        self._documents: dict[str, dict[str, Any]] = {}
        self._vocabulary: dict[str, int] = {}
        self._idf: dict[str, float] = {}
        if self.db_path and self.db_path.is_file():
            self.load()

    def _compute_vector(self, text: str) -> dict[str, float]:
        tokens = _tokenize(text)
        if not tokens:
            return {}
        tf: dict[str, int] = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1

        vec: dict[str, float] = {}
        for t, count in tf.items():
            idf = self._idf.get(t, 1.0)
            vec[t] = (count / len(tokens)) * idf

        # Normalisation L2
        norm = math.sqrt(sum(v * v for v in vec.values()))
        if norm > 0:
            vec = {k: v / norm for k, v in vec.items()}
        return vec

    def _rebuild_idf(self):
        n_docs = len(self._documents)
        if n_docs == 0:
            self._idf = {}
            return
        doc_freq: dict[str, int] = {}
        for doc in self._documents.values():
            seen = set(_tokenize(doc["text"]))
            for term in seen:
                doc_freq[term] = doc_freq.get(term, 0) + 1

        self._idf = {
            term: math.log(1.0 + (n_docs / (1.0 + freq))) + 1.0
            for term, freq in doc_freq.items()
        }

    def add_document(self, text: str, doc_id: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        uid = doc_id or hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        self._documents[uid] = {
            "id": uid,
            "text": text,
            "metadata": metadata or {},
        }
        self._rebuild_idf()
        if self.db_path:
            self.save()
        return uid

    def add_documents(self, docs: list[dict[str, Any]]) -> int:
        count = 0
        for d in docs:
            text = d.get("text", "")
            if text:
                uid = d.get("id") or hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
                self._documents[uid] = {
                    "id": uid,
                    "text": text,
                    "metadata": d.get("metadata", {}),
                }
                count += 1
        self._rebuild_idf()
        if self.db_path:
            self.save()
        return count

    def search(self, query: str, top_k: int = 3, min_score: float = 0.05) -> list[dict[str, Any]]:
        query_vec = self._compute_vector(query)
        if not query_vec or not self._documents:
            return []

        results = []
        for doc in self._documents.values():
            doc_vec = self._compute_vector(doc["text"])
            # Produit scalaire (similarité cosinus)
            score = sum(query_vec[term] * doc_vec[term] for term in query_vec if term in doc_vec)
            if score >= min_score:
                results.append({
                    "id": doc["id"],
                    "text": doc["text"],
                    "metadata": doc["metadata"],
                    "score": round(score, 4),
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def save(self):
        if not self.db_path:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "documents": list(self._documents.values()),
        }
        self.db_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def load(self):
        if not self.db_path or not self.db_path.is_file():
            return
        data = json.loads(self.db_path.read_text("utf-8"))
        for doc in data.get("documents", []):
            self._documents[doc["id"]] = doc
        self._rebuild_idf()


class RAGManager:
    """Gestionnaire de compétences RAG pour JarvisMesh."""

    def __init__(self, vector_store: Optional[LocalVectorStore] = None, llm_fn: Optional[Callable] = None):
        self.store = vector_store or LocalVectorStore()
        self.llm_fn = llm_fn

    def get_skills(self) -> dict[str, Callable]:
        """Retourne les compétences RAG à enregistrer dans un JarvisNode."""

        def rag_index(payload: dict) -> dict:
            if "documents" in payload and isinstance(payload["documents"], list):
                count = self.store.add_documents(payload["documents"])
            elif "text" in payload:
                self.store.add_document(payload["text"], doc_id=payload.get("id"), metadata=payload.get("metadata"))
                count = 1
            else:
                return {"ok": False, "error": "Champ 'text' ou 'documents' requis"}
            return {"ok": True, "indexed_count": count, "total_documents": len(self.store._documents)}

        def rag_search(payload: dict) -> dict:
            query = payload.get("query", "")
            top_k = int(payload.get("top_k", 3))
            min_score = float(payload.get("min_score", 0.05))
            results = self.store.search(query=query, top_k=top_k, min_score=min_score)
            return {"query": query, "count": len(results), "results": results}

        async def rag_ask(payload: dict) -> dict:
            question = payload.get("question") or payload.get("prompt", "")
            top_k = int(payload.get("top_k", 3))
            search_res = self.store.search(query=question, top_k=top_k)

            context_blocks = []
            sources = []
            for i, r in enumerate(search_res, 1):
                context_blocks.append(f"[{i}] {r['text']}")
                sources.append({"id": r["id"], "score": r["score"], "metadata": r["metadata"]})

            context_str = "\n\n".join(context_blocks) if context_blocks else "Aucun document pertinent trouvé."
            augmented_prompt = (
                f"Contexte documentaire :\n"
                f"---------------------\n"
                f"{context_str}\n"
                f"---------------------\n\n"
                f"Question : {question}\n\n"
                f"Réponds précisément et de manière concise à la question en exploitant les informations du contexte ci-dessus."
            )

            # Si une fonction LLM est attachée
            if self.llm_fn:
                llm_res = self.llm_fn({"prompt": augmented_prompt, "max_tokens": payload.get("max_tokens", 300)})
                if hasattr(llm_res, "__await__"):
                    llm_res = await llm_res
                answer = llm_res.get("response") if isinstance(llm_res, dict) else str(llm_res)
            else:
                answer = f"RAG Search a trouvé {len(sources)} source(s). Contexte assemblé : \n{context_str}"

            return {
                "question": question,
                "answer": answer,
                "sources": sources,
                "context_used": len(sources) > 0,
            }

        return {
            "rag_index": rag_index,
            "rag_search": rag_search,
            "rag_ask": rag_ask,
        }
