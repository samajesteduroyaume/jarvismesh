"""
Tests pour la sérialisation binaire et la compression de données (jarvismesh.binary_protocol).
"""
import pytest
from jarvismesh.core import BinaryMessageEncoder, MAGIC_BINARY_HEADER


def test_binary_encode_decode_roundtrip():
    print("\n== Test BinaryProtocol: Aller-retour encodage/décodage compressé ==")
    
    # Grand document avec répétitions (typique d'un contexte RAG ou JSON verbeux)
    payload = {
        "task_id": "test_12345",
        "skill": "rag_search",
        "context": "Intelligence Artificielle Souveraine et Distribuée " * 200,
        "embeddings": [0.123456, -0.654321, 0.987654] * 50,
        "nested": {"status": "OK", "nodes": ["mac-1", "mac-2", "linux-server"]},
    }
    
    # 1. Encodage avec compression
    encoded_bytes = BinaryMessageEncoder.encode(payload, compress=True)
    assert encoded_bytes.startswith(MAGIC_BINARY_HEADER)
    assert encoded_bytes[4] == 0x01  # flag compressed
    
    # 2. Décodage et intégrité
    decoded = BinaryMessageEncoder.decode(encoded_bytes)
    assert decoded["task_id"] == "test_12345"
    assert decoded["skill"] == "rag_search"
    assert decoded["context"] == payload["context"]
    assert decoded["embeddings"] == payload["embeddings"]
    assert decoded["nested"] == payload["nested"]
    
    # 3. Métriques de compression
    stats = BinaryMessageEncoder.get_compression_stats(payload)
    print(f"Stats compression : {stats['original_bytes']} B -> {stats['compressed_bytes']} B ({stats['ratio_percent']}% gagné)")
    assert stats["ratio_percent"] > 50.0  # Plus de 50% d'économie sur ce type de payload
