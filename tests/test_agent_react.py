"""
Tests unitaires pour l'Agent Autonome ReAct et le Function Calling Distribué.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.node import JarvisNode
from jarvismesh.skills import DEFAULT_SKILLS, DEFAULT_SCHEMAS
from jarvismesh.agent import AutonomousAgent, AgentStep, AgentTrace


async def test_react_agent_reasoning_and_tool_call():
    print("== Test 1: Boucle ReAct avec appel de compétence distribuée ==")

    # Nœud LLM simulant les étapes ReAct
    step_counter = 0

    async def mock_smart_llm(payload: dict) -> dict:
        nonlocal step_counter
        step_counter += 1
        prompt = payload.get("prompt", "")

        if step_counter == 1:
            # Étape 1 : Le LLM décide d'appeler la compétence 'reverse'
            response = (
                "Thought: L'utilisateur me demande d'inverser un message secret. Je dois utiliser la compétence 'reverse'.\n"
                "Action: {\"skill\": \"reverse\", \"payload\": {\"text\": \"ihcaM sivraJ\"}}"
            )
        else:
            # Étape 2 : Le LLM reçoit l'observation et formule la réponse finale
            response = (
                "Thought: J'ai reçu le résultat inversé 'Jarvis Machi'. Je peux maintenant conclure.\n"
                "Final Answer: Le message décodé avec succès est 'Jarvis Machi'."
            )
        return {"ok": True, "response": response}

    node_a = JarvisNode("agent-master", 9910, skills={"llm": mock_smart_llm})
    node_b = JarvisNode("agent-worker", 9911, skills={"reverse": DEFAULT_SKILLS["reverse"]})

    await node_a.start(enable_zeroconf=False)
    await node_b.start(enable_zeroconf=False)

    node_a.add_static_peer("agent-worker", "127.0.0.1", 9911, ["reverse"])

    agent = AutonomousAgent(node_a, max_steps=4, llm_skill="llm")
    steps_logged = []

    def on_step(step: AgentStep):
        steps_logged.append(step)
        print(f"  [Étape {step.step_number}] Thought: {step.thought[:60]}... | Action: {step.action_skill} | Err: {step.error}")

    trace = await agent.run("Décode le message secret 'ihcaM sivraJ'", on_step=on_step)

    assert trace.ok is True
    assert len(trace.steps) == 2
    assert "Jarvis Machi" in trace.final_answer
    assert trace.steps[0].action_skill == "reverse"
    assert trace.steps[0].observation == {"reversed": "Jarvis Machi"}
    assert trace.steps[0].handled_by == "agent-worker"

    print(f"  -> Résultat final de l'agent : {trace.final_answer}")
    print(f"  -> Durée totale : {trace.total_duration_sec:.3f}s")

    await node_a.stop()
    await node_b.stop()


async def test_react_agent_self_healing():
    print("\n== Test 2: Auto-réparation (Self-Healing) en cas d'erreur de compétence ==")

    step_counter = 0

    async def mock_self_healing_llm(payload: dict) -> dict:
        nonlocal step_counter
        step_counter += 1

        if step_counter == 1:
            # Tente une compétence qui échoue (payload vide)
            response = (
                "Thought: Je tente d'appeler reverse sans texte.\n"
                "Action: {\"skill\": \"reverse\", \"payload\": {}}"
            )
        elif step_counter == 2:
            # Observe l'erreur et s'auto-corrige
            response = (
                "Thought: L'appel précédent a échoué car le texte était vide. Je corrige le payload.\n"
                "Action: {\"skill\": \"reverse\", \"payload\": {\"text\": \"correction\"}}"
            )
        else:
            response = (
                "Thought: Tout a fonctionné.\n"
                "Final Answer: Terminé avec succès après auto-réparation."
            )
        return {"ok": True, "response": response}

    node = JarvisNode("self-heal-node", 9912, skills={
        "llm": mock_self_healing_llm,
        "reverse": DEFAULT_SKILLS["reverse"],
    }, schemas=DEFAULT_SCHEMAS)
    await node.start(enable_zeroconf=False)

    agent = AutonomousAgent(node, max_steps=5, llm_skill="llm")
    trace = await agent.run("Teste l'auto-correction")

    assert trace.ok is True
    assert len(trace.steps) == 3
    assert trace.steps[0].error is not None  # Première étape en échec
    assert trace.steps[1].error is None      # Deuxième étape corrigée
    print(f"  -> L'agent s'est auto-corrigé avec succès : {trace.final_answer}")

    await node.stop()


if __name__ == "__main__":
    asyncio.run(test_react_agent_reasoning_and_tool_call())
    asyncio.run(test_react_agent_self_healing())
    print("\nTous les tests de l'Agent Autonome ReAct sont passés avec succès !")
