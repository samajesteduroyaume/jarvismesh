"""
Tests unitaires pour l'Orchestrateur & Chaînage de tâches multi-agents.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.skills import DEFAULT_SKILLS, DEFAULT_SCHEMAS
from jarvismesh.orchestrator import Workflow, WorkflowStep


async def test_orchestrator():
    print("== Test 1: Configuration du cluster multi-nœuds ==")
    node_a = JarvisNode("node-a", 9201, skills={"echo": DEFAULT_SKILLS["echo"], "wordcount": DEFAULT_SKILLS["wordcount"]})
    node_b = JarvisNode("node-b", 9202, skills={"reverse": DEFAULT_SKILLS["reverse"]})

    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)

    node_a.add_static_peer("node-b", "127.0.0.1", 9202, ["reverse"])
    node_b.add_static_peer("node-a", "127.0.0.1", 9201, ["echo", "wordcount"])

    print("\n== Test 2: Workflow séquentiel avec interpolation de contexte ==")
    wf = Workflow("Pipeline Séquentiel", "Test du chaînage A -> B -> A")
    wf.add_step("step1_echo", skill="echo", payload={"text": "{input.phrase}"})
    wf.add_step("step2_reverse", skill="reverse", payload={"text": "{steps.step1_echo.result.echo}"})
    wf.add_step("step3_count", skill="wordcount", payload={"text": "{steps.step2_reverse.result.reversed}"})

    events_captured = []
    def on_progress(evt, step_name, data):
        events_captured.append((evt, step_name))

    result = await wf.run(node_a, initial_input={"phrase": "JarvisMesh P2P Sovereign"}, on_progress=on_progress)
    print(f"  -> ok={result.ok} duration={result.duration_sec:.3f}s")
    print(f"  -> final_output: {result.final_output}")
    print(f"  -> événements: {events_captured}")

    assert result.ok
    assert len(events_captured) == 6  # 3 start + 3 done
    assert result.step_results["step1_echo"].result["echo"] == "JarvisMesh P2P Sovereign"
    assert result.step_results["step2_reverse"].handled_by == "node-b"
    assert result.step_results["step2_reverse"].result["reversed"] == "ngierevoS P2P hseMsivraJ"
    assert result.step_results["step3_count"].result["words"] == 3

    print("\n== Test 3: Workflow avec étapes parallèles ==")
    wf_parallel = Workflow("Pipeline Parallèle")
    wf_parallel.add_step("source", skill="echo", payload={"text": "hello world from mesh"})
    wf_parallel.add_parallel_steps([
        WorkflowStep("par_reverse", skill="reverse", payload={"text": "{steps.source.result.echo}"}),
        WorkflowStep("par_count", skill="wordcount", payload={"text": "{steps.source.result.echo}"}),
    ])

    res_par = await wf_parallel.run(node_a)
    print(f"  -> ok={res_par.ok} steps={list(res_par.step_results.keys())}")
    assert res_par.ok
    assert "par_reverse" in res_par.step_results
    assert "par_count" in res_par.step_results
    assert res_par.step_results["par_reverse"].result["reversed"] == "hsem morf dlrow olleh"
    assert res_par.step_results["par_count"].result["words"] == 4

    print("\n== Test 4: Gestion d'erreur et politique on_error ==")
    # 4.1 On abort (par défaut)
    wf_fail = Workflow("Pipeline Échoué")
    wf_fail.add_step("bad_step", skill="skill_inexistante", payload={})
    wf_fail.add_step("never_reached", skill="echo", payload={"text": "pas exécuté"})
    res_fail = await wf_fail.run(node_a)
    print(f"  -> abort: ok={res_fail.ok} errors={res_fail.errors}")
    assert not res_fail.ok
    assert "never_reached" not in res_fail.step_results

    # 4.2 On continue
    wf_continue = Workflow("Pipeline Tolérant")
    wf_continue.add_step("bad_step", skill="skill_inexistante", payload={}, on_error="continue")
    wf_continue.add_step("reached", skill="echo", payload={"text": "toujours exécuté"})
    res_cont = await wf_continue.run(node_a)
    print(f"  -> continue: ok={res_cont.ok} steps={list(res_cont.step_results.keys())}")
    assert not res_cont.ok  # ok global est False car une erreur a eu lieu
    assert "reached" in res_cont.step_results  # mais l'étape suivante a bien tourné
    assert res_cont.step_results["reached"].ok is True

    await node_a.stop()
    await node_b.stop()
    print("\nTous les tests de l'orchestrateur sont passés avec succès !")


if __name__ == "__main__":
    asyncio.run(test_orchestrator())
