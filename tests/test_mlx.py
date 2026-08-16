"""
Tests de l'intégration MLX-LM dans JarvisMesh :
  1. Délégation synchrone 'llm' avec exécution locale / distante
  2. Délégation en streaming 'llm-stream' (génération token-par-token)
  3. Validation des schémas Pydantic LLMPayload
  4. Métriques de santé Metal / VRAM via la compétence interne '_health'
"""
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.protocol import HEALTH_SKILL
from jarvismesh.skills import DEFAULT_SKILLS, DEFAULT_SCHEMAS
from jarvismesh.mlx_engine import (
    MLXModelManager,
    mlx_health_extra,
    _HAS_MLX,
)


async def test_mlx_skills():
    print("== Test MLX 1: Initialisation des nœuds (A: client, B: serveur MLX) ==")
    node_a = JarvisNode("agent-client", 9001, skills={}, health_extra=mlx_health_extra)
    node_b = JarvisNode(
        "agent-mlx",
        9002,
        skills={
            "llm": DEFAULT_SKILLS["llm"],
            "llm-stream": DEFAULT_SKILLS["llm-stream"],
            "echo": DEFAULT_SKILLS["echo"],
        },
        schemas=DEFAULT_SCHEMAS,
        health_extra=mlx_health_extra,
    )

    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)

    node_a.add_static_peer("agent-mlx", "127.0.0.1", 9002, ["llm", "llm-stream", "echo"])
    node_b.add_static_peer("agent-client", "127.0.0.1", 9001, [])

    print(f"  -> MLX disponible: {_HAS_MLX}")
    print("== Test MLX 2: Délégation synchrone 'llm' ==")
    t0 = time.monotonic()
    resp = await node_a.delegate(
        "llm",
        {
            "prompt": "Réponds uniquement par le mot EXACT: 'OK'.",
            "max_tokens": 20,
            "temperature": 0.1,
        },
        peer_name="agent-mlx",
    )
    elapsed = time.monotonic() - t0
    print(f"  -> ok={resp.ok} handled_by={resp.handled_by} elapsed={elapsed:.2f}s")
    print(f"  -> résultat: {resp.result}")
    assert resp.ok
    assert isinstance(resp.result, dict)
    assert "response" in resp.result
    assert len(resp.result["response"]) > 0

    print("\n== Test MLX 3: Délégation en flux continu 'llm-stream' ==")
    chunks = []
    t0 = time.monotonic()
    resp_stream = await node_a.delegate_stream(
        "llm-stream",
        {
            "prompt": "Compte de 1 à 3.",
            "max_tokens": 30,
            "temperature": 0.1,
        },
        on_chunk=chunks.append,
        peer_name="agent-mlx",
    )
    elapsed_stream = time.monotonic() - t0
    full_text = "".join(chunks)
    print(f"  -> ok={resp_stream.ok} streamed={resp_stream.streamed} chunks_count={len(chunks)} elapsed={elapsed_stream:.2f}s")
    print(f"  -> texte assemblé: {repr(full_text)}")
    assert resp_stream.ok
    assert resp_stream.streamed
    assert len(chunks) > 1

    print("\n== Test MLX 4: Validation Pydantic sur LLMPayload ==")
    # 4.1 Rejet si payload vide (aucun prompt ni messages)
    bad_resp = await node_a.delegate("llm", {}, peer_name="agent-mlx")
    print(f"  -> Rejet payload vide: ok={bad_resp.ok} error={bad_resp.error}")
    assert not bad_resp.ok
    assert "payload invalide" in bad_resp.error

    # 4.2 Rejet si prompt est une chaîne vide
    empty_resp = await node_a.delegate("llm", {"prompt": ""}, peer_name="agent-mlx")
    print(f"  -> Rejet prompt vide: ok={empty_resp.ok} error={empty_resp.error}")
    assert not empty_resp.ok
    assert "payload invalide" in empty_resp.error

    # 4.3 Support des messages structurés (chat)
    chat_resp = await node_a.delegate(
        "llm",
        {
            "messages": [
                {"role": "system", "content": "Tu es un assistant concis."},
                {"role": "user", "content": "Dis 'Bonjour'"},
            ],
            "max_tokens": 15,
        },
        peer_name="agent-mlx",
    )
    print(f"  -> Messages structurés: ok={chat_resp.ok} result={chat_resp.result}")
    assert chat_resp.ok

    print("\n== Test MLX 5: Métriques de santé et mémoire Metal (_health) ==")
    health_resp = await node_a.delegate(HEALTH_SKILL, {}, peer_name="agent-mlx")
    print(f"  -> ok={health_resp.ok} result={health_resp.result}")
    assert health_resp.ok
    assert "mlx_available" in health_resp.result
    assert health_resp.result["mlx_available"] is True
    if "metal_active_mb" in health_resp.result:
        print(f"  -> VRAM active: {health_resp.result.get('metal_active_mb')} MB, pic: {health_resp.result.get('metal_peak_mb')} MB")

    await node_a.stop()
    await node_b.stop()
    print("\nTous les tests MLX sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_mlx_skills())
