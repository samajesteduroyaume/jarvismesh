"""
Tests unitaires pour le chiffrement de bout en bout (E2EE) X25519 / ChaCha20-Poly1305.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from jarvismesh.e2ee import (
    E2EEIdentity,
    E2EESession,
    encrypt_for_peer,
    decrypt_from_peer,
)


def test_e2ee_key_derivation_and_encryption():
    print("== Test 1: Génération des identités X25519 ==")
    node_alice = E2EEIdentity.generate()
    node_bob = E2EEIdentity.generate()

    assert len(node_alice.public_key_bytes) == 32
    assert len(node_bob.public_key_bytes) == 32
    assert node_alice.public_key_hex != node_bob.public_key_hex

    print("== Test 2: Dérivation d'une clé symétrique partagée (Diffie-Hellman) ==")
    key_alice = node_alice.derive_shared_key(node_bob.public_key_hex)
    key_bob = node_bob.derive_shared_key(node_alice.public_key_hex)

    assert key_alice == key_bob
    assert len(key_alice) == 32

    print("== Test 3: Chiffrement et déchiffrement de session ChaCha20-Poly1305 ==")
    session_alice = E2EESession(key_alice)
    session_bob = E2EESession(key_bob)

    payload = {
        "secret_task": "Inférence LLM confidentielle",
        "tokens": [102, 304, 506],
        "node_id": "secure-cluster-1"
    }

    envelope = session_alice.encrypt(payload)
    print(f"  -> Ciphertext chiffré (base64): {envelope['ciphertext'][:30]}...")
    assert envelope.get("e2ee") is True
    assert "ciphertext" in envelope
    assert "nonce" in envelope

    decrypted = session_bob.decrypt(envelope)
    assert decrypted == payload
    assert decrypted["secret_task"] == "Inférence LLM confidentielle"


def test_asymmetric_peer_helpers():
    print("\n== Test 4: Chiffrement/Déchiffrement asymétrique complet pour un pair ==")
    bob_identity = E2EEIdentity.generate()
    secret_message = {"directive": "Execute secure workflow", "authorized": True}

    # Alice chiffre directement pour Bob sans session pré-établie
    encrypted_envelope = encrypt_for_peer(bob_identity.public_key_hex, secret_message)
    assert encrypted_envelope["sender_pubkey"] != ""

    # Bob déchiffre avec sa clé privée
    recovered_message = decrypt_from_peer(encrypted_envelope, bob_identity)
    assert recovered_message == secret_message
    print(f"  -> Message déchiffré par Bob : {recovered_message}")


if __name__ == "__main__":
    test_e2ee_key_derivation_and_encryption()
    test_asymmetric_peer_helpers()
    print("\nTous les tests E2EE sont passés avec succès !")
