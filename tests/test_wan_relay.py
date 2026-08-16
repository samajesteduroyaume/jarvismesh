"""
Tests unitaires pour l'interconnexion WAN et le serveur de relais MeshRelayServer.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.core import JarvisNode, MeshRelayServer, WANPeerManager


async def test_wan_relay():
    print("== Test 1: Démarrage du serveur de relais WAN MeshRelayServer ==")
    relay = MeshRelayServer(host="127.0.0.1", port=9700)
    await relay.start()

    print("== Test 2: Démarrage de Node A et Node B sans mDNS (découverte WAN pure) ==")
    node_a = JarvisNode("wan-agent-a", 9701, skills={"echo": lambda p: {"echo": p.get("text")}}, advertise_ip="127.0.0.1")
    node_b = JarvisNode("wan-agent-b", 9702, skills={"reverse": lambda p: {"rev": p.get("text", "")[::-1]}}, advertise_ip="127.0.0.1")

    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)

    wan_a = WANPeerManager(node_a, relay_url="http://127.0.0.1:9700", sync_interval=1.0)
    wan_b = WANPeerManager(node_b, relay_url="http://127.0.0.1:9700", sync_interval=1.0)

    await wan_a.start()
    await wan_b.start()

    print("== Test 3: Synchronisation des pairs distants via le relais ==")
    await asyncio.sleep(1.5)  # Laisser le temps à l'enregistrement et découverte

    print(f"  -> Pairs découverts par Node A : {list(node_a.peers.keys())}")
    print(f"  -> Pairs découverts par Node B : {list(node_b.peers.keys())}")
    assert "wan-agent-b" in node_a.peers
    assert "wan-agent-a" in node_b.peers

    print("\n== Test 4: Délégation WAN A -> B ==")
    resp = await node_a.delegate("reverse", {"text": "TailscaleWAN"})
    print(f"  -> ok={resp.ok} handled_by={resp.handled_by} result={resp.result}")
    assert resp.ok is True
    assert resp.handled_by == "wan-agent-b"
    assert resp.result["rev"] == "NAWelacsliaT"

    await wan_a.stop()
    await wan_b.stop()
    await node_a.stop()
    await node_b.stop()
    await relay.stop()
    print("\nTous les tests du relais WAN sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_wan_relay())
