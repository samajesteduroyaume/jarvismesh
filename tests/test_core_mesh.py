import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.core import JarvisNode
from jarvismesh.skills import DEFAULT_SKILLS


async def test_core_mesh():
    # Noeud A ne sait que "echo" et "wordcount"
    node_a = JarvisNode("agent-a", 8801, skills={
        "echo": DEFAULT_SKILLS["echo"],
        "wordcount": DEFAULT_SKILLS["wordcount"],
    })
    # Noeud B ne sait que "reverse" et "llm"
    node_b = JarvisNode("agent-b", 8802, skills={
        "reverse": DEFAULT_SKILLS["reverse"],
        "llm": DEFAULT_SKILLS["llm"],
        "llm-stream": DEFAULT_SKILLS["llm-stream"],
        "slow-echo": DEFAULT_SKILLS["slow-echo"],
    })

    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)

    # Découverte manuelle (simule ce que ferait zeroconf sur un vrai LAN)
    node_a.add_static_peer("agent-b", "127.0.0.1", 8802, ["reverse", "llm", "llm-stream", "slow-echo"])
    node_b.add_static_peer("agent-a", "127.0.0.1", 8801, ["echo", "wordcount"])

    print("== Test 1: A délègue 'reverse' à B (A ne sait pas le faire) ==")
    resp = await node_a.delegate("reverse", {"text": "JarvisMesh"})
    print(f"  -> ok={resp.ok} handled_by={resp.handled_by} result={resp.result}")
    assert resp.ok and resp.result["reversed"] == "hseMsivraJ"

    print("== Test 2: B délègue 'wordcount' à A ==")
    resp = await node_b.delegate("wordcount", {"text": "un protocole sans cloud"})
    print(f"  -> ok={resp.ok} handled_by={resp.handled_by} result={resp.result}")
    assert resp.ok and resp.result["words"] == 4

    print("== Test 3: A exécute 'echo' en LOCAL (pas de réseau nécessaire) ==")
    resp = await node_a.delegate("echo", {"text": "je suis local"})
    print(f"  -> ok={resp.ok} handled_by={resp.handled_by} result={resp.result}")
    assert resp.ok and resp.handled_by == "agent-a"

    print("== Test 4: A demande une compétence que personne n'a ==")
    resp = await node_a.delegate("skill-inexistante", {})
    print(f"  -> ok={resp.ok} error={resp.error}")
    assert not resp.ok

    print("== Test 5: A délègue 'llm-stream' à B, en streaming ==")
    chunks_received = []
    resp = await node_a.delegate_stream(
        "llm-stream", {"prompt": "salut"}, on_chunk=chunks_received.append
    )
    print(f"  -> chunks reçus au fil de l'eau: {chunks_received}")
    print(f"  -> ok={resp.ok} streamed={resp.streamed} result final={resp.result} error={resp.error}")
    assert resp.ok and resp.streamed and len(chunks_received) > 1
    assert resp.result == chunks_received  # le serveur renvoie l'agrégat en fin de flux

    print("== Test 6: connexion persistante réutilisée entre deux appels ==")
    await node_a.delegate("reverse", {"text": "un"}, peer_name="agent-b")
    ws_first = node_a._pool["agent-b"]
    await node_a.delegate("reverse", {"text": "deux"}, peer_name="agent-b")
    ws_second = node_a._pool["agent-b"]
    print(f"  -> même connexion réutilisée: {ws_first is ws_second}")
    assert ws_first is ws_second

    print("== Test 7: multiplexage — 'echo' rapide envoyé après 'slow-echo' (2s) ne doit PAS attendre ==")
    t0 = time.monotonic()
    slow_task = asyncio.ensure_future(node_a.delegate("slow-echo", {"text": "lent", "delay": 2.0}, peer_name="agent-b"))
    await asyncio.sleep(0.1)  # s'assure que la requête lente part bien en premier
    fast_resp = await node_a.delegate("reverse", {"text": "rapide"}, peer_name="agent-b")
    fast_elapsed = time.monotonic() - t0
    print(f"  -> réponse rapide reçue en {fast_elapsed:.2f}s (doit être << 2s)")
    assert fast_resp.ok and fast_elapsed < 1.0, "la requête rapide a été bloquée par la lente !"
    slow_resp = await slow_task
    slow_elapsed = time.monotonic() - t0
    print(f"  -> réponse lente reçue en {slow_elapsed:.2f}s, ok={slow_resp.ok}")
    assert slow_resp.ok and slow_resp.result["delay"] == 2.0

    print("== Test 8: failover — un pair mort dans la liste, bascule automatique sur l'autre ==")
    node_a.add_static_peer("agent-ghost", "127.0.0.1", 9999, ["ghost-skill"])  # personne n'écoute ici
    node_c = JarvisNode("agent-c", 8803, skills={"ghost-skill": DEFAULT_SKILLS["echo"]})
    await node_c.start(enable_zeroconf=False)
    node_a.add_static_peer("agent-c", "127.0.0.1", 8803, ["ghost-skill"])
    # agent-a n'a PAS "ghost-skill" en local -> forcément délégué à un pair.
    # 2 candidats: agent-ghost (mort) et agent-c (vivant) -> le round-robin
    # doit finir par réussir sur agent-c à chaque appel, quel que soit
    # l'ordre de tentative.
    ok_count = 0
    for _ in range(4):
        resp = await node_a.delegate("ghost-skill", {"text": "failover"})
        print(f"    intent: ok={resp.ok} handled_by={resp.handled_by} error={resp.error}")
        if resp.ok:
            ok_count += 1
            assert resp.handled_by == "agent-c"
    print(f"  -> {ok_count}/4 appels ont fini par réussir via failover sur agent-c")
    assert ok_count == 4
    await node_c.stop()

    await node_a.stop()
    await node_b.stop()
    print("\nTous les tests sont passés.")


if __name__ == "__main__":
    asyncio.run(test_core_mesh())
