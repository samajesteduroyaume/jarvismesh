"""
Tests unitaires pour la mémoire partagée et le RAG local (LocalVectorStore & RAGManager).
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.core import JarvisNode
from jarvismesh.memory import LocalVectorStore, RAGManager


async def test_rag():
    print("== Test 1: Indexation et recherche dans LocalVectorStore ==")
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_file = Path(tmp_dir) / "test_store.json"
        store = LocalVectorStore(db_file)

        docs = [
            {"id": "doc1", "text": "JarvisMesh est un protocole d'agents IA locaux et souverain sur réseau local."},
            {"id": "doc2", "text": "Apple Silicon exploite l'accélération Metal et la mémoire unifiée pour exécuter des modèles MLX."},
            {"id": "doc3", "text": "La recette de la tarte aux pommes nécessite des pommes, du sucre et de la pâte feuilletée."},
        ]
        indexed = store.add_documents(docs)
        print(f"  -> {indexed} documents indexés dans {db_file}")
        assert indexed == 3

        # Recherche sémantique
        results_mesh = store.search("protocole réseau agents souverain", top_k=1)
        print(f"  -> Recherche 'protocole réseau': top match = {results_mesh[0]['id']} (score: {results_mesh[0]['score']})")
        assert results_mesh[0]["id"] == "doc1"

        results_apple = store.search("Metal GPU MLX Mac", top_k=1)
        print(f"  -> Recherche 'Metal GPU': top match = {results_apple[0]['id']} (score: {results_apple[0]['score']})")
        assert results_apple[0]["id"] == "doc2"

        print("\n== Test 2: Persistance et rechargement ==")
        reloaded_store = LocalVectorStore(db_file)
        assert len(reloaded_store._documents) == 3
        res_reload = reloaded_store.search("pommes tarte sucre", top_k=1)
        assert res_reload[0]["id"] == "doc3"
        print("  -> Persistance sur disque vérifiée avec succès")

        print("\n== Test 3: Compétences RAG intégrées dans JarvisNode ==")
        rag_mgr = RAGManager(store)
        node = JarvisNode("rag-node", 9601, skills=rag_mgr.get_skills())
        await node.start(enable_zeroconf=False)

        # 3.1 rag_search
        search_resp = await node.delegate("rag_search", {"query": "Apple Silicon Metal", "top_k": 2})
        print(f"  -> rag_search: ok={search_resp.ok} count={search_resp.result['count']}")
        assert search_resp.ok is True
        assert search_resp.result["count"] >= 1

        # 3.2 rag_index
        idx_resp = await node.delegate("rag_index", {"text": "Python 3.11 apporte des optimisations majeures de vitesse.", "id": "doc4"})
        print(f"  -> rag_index: ok={idx_resp.ok} total={idx_resp.result['total_documents']}")
        assert idx_resp.ok is True
        assert idx_resp.result["total_documents"] == 4

        # 3.3 rag_ask
        ask_resp = await node.delegate("rag_ask", {"question": "Comment MLX tire parti de Metal ?"})
        print(f"  -> rag_ask: ok={ask_resp.ok} sources={len(ask_resp.result['sources'])}")
        assert ask_resp.ok is True
        assert ask_resp.result["context_used"] is True

        await node.stop()

    print("\nTous les tests du moteur RAG sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_rag())
