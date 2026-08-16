"""
Tests pour le re-classement sémantique et le graphe de connaissances (GraphRAG).
"""
import pytest
from jarvismesh.memory import SemanticReranker, get_reranker_skills
from jarvismesh.memory import KnowledgeGraphStore, get_graph_skills


def test_semantic_reranker():
    print("\n== Test SemanticReranker: Scoring croisé et reclassement ==")
    reranker = SemanticReranker()
    
    query = "chiffrement de bout en bout X25519"
    candidates = [
        {"id": "doc1", "text": "La météo d'aujourd'hui est très ensoleillée à Paris."},
        {"id": "doc2", "text": "Le chiffrement de bout en bout utilise X25519 et ChaCha20-Poly1305 pour la sécurité."},
        {"id": "doc3", "text": "Le protocole de communication utilise des WebSockets asynchrones."},
    ]
    
    results = reranker.rerank(query, candidates, top_k=2)
    assert len(results) == 2
    assert results[0]["id"] == "doc2"
    assert results[0]["rerank_score"] > results[1]["rerank_score"]


def test_knowledge_graph_store():
    print("\n== Test KnowledgeGraphStore: Triples, relations et chemins BFS ==")
    graph = KnowledgeGraphStore(":memory:")
    
    # Ingestion de relations
    graph.add_triple("MacBook-M3", "execute", "MLX-Engine")
    graph.add_triple("MLX-Engine", "accelere", "Metal-GPU")
    graph.add_triple("MacBook-M3", "connecte", "Relais-WAN")
    
    # 1. Requête relationnelle
    out_relations = graph.query_relations("MacBook-M3", direction="out")
    assert len(out_relations) == 2
    
    # 2. Recherche de chemin multi-sauts (BFS)
    paths = graph.find_path("MacBook-M3", "Metal-GPU", max_depth=3)
    assert len(paths) >= 1
    assert paths[0] == ["MacBook-M3", "MLX-Engine", "Metal-GPU"]
    
    # 3. Statistiques
    stats = graph.count()
    assert stats["entities"] >= 4
    assert stats["triples"] == 3
    
    graph.close()


async def test_reranker_and_graph_skills():
    print("\n== Test Skills: Compétences mesh Rerank et Graph ==")
    rerank_skills = get_reranker_skills()
    graph_skills = get_graph_skills()
    
    # Skill Rerank
    res_rerank = await rerank_skills["rag_rerank"]({
        "query": "intelligence artificielle distribuée",
        "candidates": [
            {"id": "a", "text": "Ceci est une recette de cuisine."},
            {"id": "b", "text": "JarvisMesh propose une intelligence artificielle distribuée sur le réseau."},
        ],
        "top_k": 1,
    })
    assert res_rerank["ok"] is True
    assert res_rerank["results"][0]["id"] == "b"
    
    # Skill Graph Store & Query
    store_res = await graph_skills["graph_store_triple"]({
        "subject": "Agent-Alpha",
        "predicate": "delegue",
        "object": "Agent-Beta",
    })
    assert store_res["ok"] is True
    
    query_res = await graph_skills["graph_query_relations"]({
        "entity": "Agent-Alpha",
        "direction": "out",
    })
    assert query_res["ok"] is True
    assert len(query_res["relations"]) == 1
    assert query_res["relations"][0]["object"] == "Agent-Beta"
