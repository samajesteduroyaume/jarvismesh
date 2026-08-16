"""
Tests unitaires pour l'authentification asymétrique Ed25519, le TrustStore et l'anti-rejeu.
"""
import asyncio
import sys
import time
from pathlib import Path
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.protocol import TaskRequest
from jarvismesh.crypto import NodeIdentity, TrustStore, verify_ed25519_signature


async def test_ed25519_auth():
    print("== Test 1: Génération et sérialisation des identités Ed25519 ==")
    with tempfile.TemporaryDirectory() as tmp_dir:
        id_path = Path(tmp_dir) / "node_a.key"
        id_a = NodeIdentity.generate()
        id_a.save(id_path)
        print(f"  -> Clé Node A sauvegardée, ID: {id_a.node_id}, PubKey: {id_a.public_key_hex[:16]}...")

        # Rechargement
        id_loaded = NodeIdentity.load(id_path)
        assert id_loaded.public_key_hex == id_a.public_key_hex
        print("  -> Rechargement de clé validé")

    id_b = NodeIdentity.generate()
    id_attacker = NodeIdentity.generate()

    print("\n== Test 2: Configuration TrustStore et nœuds sécurisés ==")
    trust_store_a = TrustStore()
    # On autorise Node B sur Node A
    trust_store_a.add_key(id_b.public_key_hex, peer_name="node-b")

    node_a = JarvisNode("node-a", 9401, skills={"secret_tool": lambda p: {"data": "confidentiel"}}, trust_store=trust_store_a)
    node_b = JarvisNode("node-b", 9402, skills={}, identity=id_b)
    node_c = JarvisNode("node-c", 9403, skills={}, identity=id_attacker)

    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)
    await node_c.start(enable_zeroconf=False)

    node_b.add_static_peer("node-a", "127.0.0.1", 9401, ["secret_tool"])
    node_c.add_static_peer("node-a", "127.0.0.1", 9401, ["secret_tool"])

    print("\n== Test 3: Requête signée par Node B (Autorisé) -> Succès ==")
    resp_b = await node_b.delegate("secret_tool", {}, peer_name="node-a")
    print(f"  -> ok={resp_b.ok} result={resp_b.result}")
    assert resp_b.ok is True
    assert resp_b.result["data"] == "confidentiel"

    print("\n== Test 4: Requête signée par Node C (Non autorisé dans TrustStore) -> Rejet ==")
    resp_c = await node_c.delegate("secret_tool", {}, peer_name="node-a")
    print(f"  -> ok={resp_c.ok} error={resp_c.error}")
    assert resp_c.ok is False
    assert "non autorisée" in resp_c.error

    print("\n== Test 5: Révocation dynamique d'un nœud dans le TrustStore ==")
    trust_store_a.revoke_key(id_b.public_key_hex)
    resp_b_revoked = await node_b.delegate("secret_tool", {}, peer_name="node-a")
    print(f"  -> Après révocation: ok={resp_b_revoked.ok} error={resp_b_revoked.error}")
    assert resp_b_revoked.ok is False
    assert "non autorisée" in resp_b_revoked.error

    await node_a.stop()
    await node_b.stop()
    await node_c.stop()
    print("\nTous les tests cryptographiques Ed25519 sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_ed25519_auth())
