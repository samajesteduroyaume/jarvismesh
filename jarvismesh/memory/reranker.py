"""
Module de Re-classement Sémantique (Semantic Reranking) pour JarvisMesh.

Permet d'appliquer une passe de scoring croisé (cross-encoder) sur les candidats
extraits de la base vectorielle pour classer les documents avec une précision maximale.
"""
from __future__ import annotations
import math
import re
from typing import Any, Callable, List, Optional


def _tokenize(text: str) -> list[str]:
    return re.findall(r"\b\w+\b", text.lower())


class SemanticReranker:
    """Moteur de scoring croisé pour le re-classement de documents pertinents."""

    def __init__(self, exact_match_weight: float = 2.0, position_weight: float = 1.2):
        self.exact_match_weight = exact_match_weight
        self.position_weight = position_weight

    def score(self, query: str, document_text: str) -> float:
        """Calcule un score de pertinence fine entre une requête et un document."""
        if not query or not document_text:
            return 0.0

        q_tokens = _tokenize(query)
        d_tokens = _tokenize(document_text)

        if not q_tokens or not d_tokens:
            return 0.0

        score = 0.0

        # 1. Présence des termes et fréquence pondérée
        d_set = set(d_tokens)
        matched_tokens = 0
        for idx, tok in enumerate(q_tokens):
            if tok in d_set:
                matched_tokens += 1
                # Les premiers mots de la requête ont un poids légèrement supérieur
                score += 1.0 + (1.0 / (idx + 1)) * self.position_weight

        # 2. Bonus de séquence exacte (n-grammes contigus)
        q_str = " ".join(q_tokens)
        d_str = " ".join(d_tokens)
        if q_str in d_str:
            score += self.exact_match_weight * len(q_tokens)

        # 3. Ratio de couverture de la requête
        coverage = matched_tokens / len(q_tokens)
        score *= (0.5 + 0.5 * coverage)

        # 4. Normalisation de longueur (légère pénalité logarithmique si trop long)
        length_pen = 1.0 / math.log(2.0 + len(d_tokens) / 10.0)
        final_score = score * length_pen

        # Sigmoïde pour borner entre 0.0 et 1.0
        return round(1.0 / (1.0 + math.exp(-final_score / 3.0)), 4)

    def rerank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        top_k: int = 3,
        min_relevance: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Re-classe une liste de dictionnaires de documents candidats."""
        scored = []
        for doc in candidates:
            text = doc.get("text", "")
            cross_score = self.score(query, text)
            if cross_score >= min_relevance:
                item = dict(doc)
                item["rerank_score"] = cross_score
                scored.append(item)

        scored.sort(key=lambda x: x["rerank_score"], reverse=True)
        return scored[:top_k]


def get_reranker_skills(reranker: Optional[SemanticReranker] = None) -> dict[str, Callable]:
    """Expose la compétence de reranking sur le maillage."""
    engine = reranker or SemanticReranker()

    async def rag_rerank(payload: dict) -> dict:
        query = payload.get("query", "")
        candidates = payload.get("candidates", [])
        top_k = int(payload.get("top_k", 3))
        if not query or not candidates:
            return {"ok": False, "error": "Les champs 'query' et 'candidates' sont requis."}

        results = engine.rerank(query, candidates, top_k=top_k)
        return {"ok": True, "results": results, "count": len(results)}

    return {"rag_rerank": rag_rerank}
