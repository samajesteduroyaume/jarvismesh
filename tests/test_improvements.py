"""
Tests des 5 axes d'amélioration :
  1. Authentification PSK/HMAC
  2. Introspection _describe_skills (contourne la limite TXT mDNS)
  3. Validation de payload par schéma Pydantic
  4. Routage par santé (_health) au lieu du round-robin aveugle
  5. (packaging: voir pyproject.toml, rien à tester à l'exécution)

Ne dépend pas de test_core_mesh.py : peut être lancé isolément.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.protocol import DESCRIBE_SKILL, HEALTH_SKILL
from jarvismesh.skills import DEFAULT_SKILLS, DEFAULT_SCHEMAS


async def test_auth():
    print("== Test A1: authentification PSK — bon psk des deux côtés ==")
    server = JarvisNode("srv-auth", 8901, skills={"echo": DEFAULT_SKILLS["echo"]}, psk="secret123")
    client = JarvisNode("cli-auth", 8902, skills={}, psk="secret123")
    await server.start(enable_zeroconf=False)
    await client.start(enable_zeroconf=False)
    client.add_static_peer("srv-auth", "127.0.0.1", 8901, ["echo"])

    resp = await client.delegate("echo", {"text": "salut"}, peer_name="srv-auth")
    print(f"  -> ok={resp.ok} result={resp.result}")
    assert resp.ok and resp.result["echo"] == "salut"

    print("== Test A2: authentification PSK — mauvais psk côté client -> rejet ==")
    bad_client = JarvisNode("cli-bad", 8903, skills={}, psk="mauvaise-cle")
    await bad_client.start(enable_zeroconf=False)
    bad_client.add_static_peer("srv-auth", "127.0.0.1", 8901, ["echo"])
    resp = await bad_client.delegate("echo", {"text": "intrus"}, peer_name="srv-auth")
    print(f"  -> ok={resp.ok} error={resp.error}")
    assert not resp.ok and "authentification" in resp.error

    print("== Test A3: authentification PSK — aucun psk côté client -> rejet ==")
    open_client = JarvisNode("cli-open", 8904, skills={})
    await open_client.start(enable_zeroconf=False)
    open_client.add_static_peer("srv-auth", "127.0.0.1", 8901, ["echo"])
    resp = await open_client.delegate("echo", {"text": "sans psk"}, peer_name="srv-auth")
    print(f"  -> ok={resp.ok} error={resp.error}")
    assert not resp.ok and "authentification" in resp.error

    await server.stop()
    await client.stop()
    await bad_client.stop()
    await open_client.stop()
    print("  -> OK\n")


async def test_describe_skills():
    print("== Test B1: introspection _describe_skills (compétence interne réservée) ==")
    node_a = JarvisNode("srv-describe", 8905, skills={
        "echo": DEFAULT_SKILLS["echo"], "reverse": DEFAULT_SKILLS["reverse"],
    })
    node_b = JarvisNode("cli-describe", 8906, skills={})
    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)
    # Le pair n'a, volontairement, qu'une liste TRONQUÉE dans son cache
    # (comme le serait un TXT record mDNS saturé) : _describe_skills doit
    # permettre de récupérer la vraie liste à la demande.
    node_b.add_static_peer("srv-describe", "127.0.0.1", 8905, ["echo"])  # 'reverse' manquant exprès

    resp = await node_b.delegate(DESCRIBE_SKILL, {}, peer_name="srv-describe")
    print(f"  -> ok={resp.ok} result={resp.result}")
    assert resp.ok and set(resp.result["skills"]) == {"echo", "reverse"}

    await node_a.stop()
    await node_b.stop()
    print("  -> OK\n")


async def test_validation():
    print("== Test C1: validation Pydantic — payload valide ==")
    node = JarvisNode("srv-valid", 8907, skills={"reverse": DEFAULT_SKILLS["reverse"]},
                       schemas=DEFAULT_SCHEMAS)
    await node.start(enable_zeroconf=False)
    resp = await node.delegate("reverse", {"text": "abc"})
    print(f"  -> ok={resp.ok} result={resp.result}")
    assert resp.ok and resp.result["reversed"] == "cba"

    print("== Test C2: validation Pydantic — payload invalide (champ manquant) ==")
    resp = await node.delegate("reverse", {})
    print(f"  -> ok={resp.ok} error={resp.error}")
    assert not resp.ok and "payload invalide" in resp.error

    print("== Test C3: validation Pydantic — payload invalide (texte vide) ==")
    resp = await node.delegate("reverse", {"text": ""})
    print(f"  -> ok={resp.ok} error={resp.error}")
    assert not resp.ok and "payload invalide" in resp.error

    print("== Test C4: validation Pydantic — rejet côté réseau (pas seulement en local) ==")
    client = JarvisNode("cli-valid", 8908, skills={})
    await client.start(enable_zeroconf=False)
    client.add_static_peer("srv-valid", "127.0.0.1", 8907, ["reverse"])
    resp = await client.delegate("reverse", {"text": 123}, peer_name="srv-valid")
    print(f"  -> ok={resp.ok} error={resp.error}")
    assert not resp.ok and "payload invalide" in resp.error

    await node.stop()
    await client.stop()
    print("  -> OK\n")


async def test_health_routing():
    print("== Test D1: routage par santé — le pair le moins chargé est préféré ==")
    busy = JarvisNode("agent-busy", 8909, skills={"echo": DEFAULT_SKILLS["echo"]})
    idle = JarvisNode("agent-idle", 8910, skills={"echo": DEFAULT_SKILLS["echo"]})
    router = JarvisNode("router", 8911, skills={})
    await busy.start(enable_zeroconf=False)
    await idle.start(enable_zeroconf=False)
    await router.start(enable_zeroconf=False)
    router.add_static_peer("agent-busy", "127.0.0.1", 8909, ["echo"])
    router.add_static_peer("agent-idle", "127.0.0.1", 8910, ["echo"])

    # On simule une charge réelle sur 'agent-busy' et on force le
    # sondage immédiat (au lieu d'attendre le prochain tick périodique)
    # pour que _ordered_candidates dispose de métriques fraîches.
    busy._active_tasks = 5
    for peer_name in ("agent-busy", "agent-idle"):
        resp = await router._send_request(peer_name, HEALTH_SKILL, {}, timeout=2.0, on_chunk=None)
        router._peer_health[peer_name] = {**resp.result, "ts": __import__("time").time()}

    candidates = router._ordered_candidates("echo")
    print(f"  -> ordre des candidats (charge décroissante attendue en dernier): {candidates}")
    assert candidates[0] == "agent-idle", "le pair le moins chargé devrait être en tête"

    await busy.stop()
    await idle.stop()
    await router.stop()
    print("  -> OK\n")


async def main():
    await test_auth()
    await test_describe_skills()
    await test_validation()
    await test_health_routing()
    print("Tous les tests des axes d'amélioration sont passés.")


if __name__ == "__main__":
    asyncio.run(main())
