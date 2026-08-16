"""
Tests unitaires pour la mémoire persistante SQLite et les embeddings denses.
"""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.memory import (
    DenseEmbeddingEngine,
    SQLiteVectorStore,
    ConversationMemory,
    MemorySkillsManager,
)


def test_dense_embeddings():
    print("== Test 1: Moteur d'embeddings denses normalisés ==")
    engine = DenseEmbeddingEngine(dimension=128)

    v1 = engine.embed("Inférence Apple Silicon avec accélération GPU Metal")
    v2 = engine.embed("Modèle d'inférence exécuté sur Apple Silicon GPU Metal")
    v3 = engine.embed("Recette de cuisine pour tarte aux pommes de terre")

    assert len(v1) == 128
    assert len(v2) == 128

    from jarvismesh.memory import _cosine_similarity
    score_proche = _cosine_similarity(v1, v2)
    score_loin = _cosine_similarity(v1, v3)

    print(f"  -> Score sémantique Silicon/Metal: {score_proche:.4f} vs Cuisine: {score_loin:.4f}")
    assert score_proche > score_loin


def test_sqlite_vector_store():
    print("\n== Test 2: Persistance SQLite Vector Store ==")
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_memory.db"
        store = SQLiteVectorStore(db_path)

        doc1_id = store.add_document("Chiffrement asymétrique Ed25519 et X25519", metadata={"topic": "crypto"})
        doc2_id = store.add_document("Accélération GPU Metal sur Apple Silicon avec MLX-LM", metadata={"topic": "metal"})
        doc3_id = store.add_document("Protocole Gossip SWIM pour cluster distribué", metadata={"topic": "network"})

        assert store.count() == 3

        # Recherche
        results = store.search("Metal Apple Silicon GPU", top_k=2)
        print(f"  -> Meilleur résultat: [{results[0]['id']}] {results[0]['text']} (Score: {results[0]['score']})")
        assert results[0]["id"] == doc2_id

        store.close()

        # Réouverture et vérification de la persistance
        store_reloaded = SQLiteVectorStore(db_path)
        assert store_reloaded.count() == 3
        store_reloaded.close()


async def test_conversation_memory_and_mesh_skills():
    print("\n== Test 3: Mémoire Épisodique & Compétences Mesh ==")
    store = SQLiteVectorStore(":memory:")
    memory = ConversationMemory(store)

    memory.add_turn("session_42", "user", "Mon nom d'agent préféré est Jarvis.")
    memory.add_turn("session_42", "assistant", "C'est noté, je m'en souviendrai.")
    memory.add_turn("session_42", "user", "Je travaille sur un Mac M3 Max avec 36 Go de RAM unifiée.")

    # Rappel
    recalled = memory.recall("Comment s'appelle l'agent et quelle est la configuration ?", session_id="session_42")
    assert len(recalled) > 0
    print(f"  -> Souvenir rappelé: \"{recalled[0]['content']}\" (Score: {recalled[0]['score']})")

    # Intégration dans JarvisNode
    skills_mgr = MemorySkillsManager(memory)
    node = JarvisNode("memory-node", 9901, skills=skills_mgr.get_skills())
    await node.start(enable_zeroconf=False)

    # Appel distant de memory_store
    resp_store = await node.delegate("memory_store", {
        "text": "La clé de sécurité principale a été renouvelée.",
        "session_id": "sec_session",
        "role": "system",
    })
    assert resp_store.ok is True
    assert resp_store.result.get("stored") is True

    # Appel distant de memory_recall
    resp_recall = await node.delegate("memory_recall", {
        "query": "clé de sécurité",
        "session_id": "sec_session",
    })
    assert resp_recall.ok is True
    assert len(resp_recall.result.get("memories", [])) >= 1

    await node.stop()
    store.close()


if __name__ == "__main__":
    test_dense_embeddings()
    test_sqlite_vector_store()
    asyncio.run(test_conversation_memory_and_mesh_skills())
    print("\nTous les tests de mémoire SQLite sont passés avec succès !")
