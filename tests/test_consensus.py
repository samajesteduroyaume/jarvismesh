"""
Tests pour le consensus et débat multi-agents (jarvismesh.consensus).
"""
import pytest
from jarvismesh.consensus import MultiAgentConsensus, AgentVote


async def test_multiagent_majority_and_weighted_vote():
    print("\n== Test MultiAgentConsensus: Vote majoritaire et pondéré ==")
    engine = MultiAgentConsensus()
    
    # 3 agents votants
    async def voter_a(p: dict):
        return {"response": "Option A est la plus robuste."}
    
    async def voter_b(p: dict):
        return {"response": "Je choisis Option B pour la performance."}
    
    async def voter_c(p: dict):
        return {"response": "Option A sans hésiter."}
    
    # Vote majoritaire simple : Option A gagne 2 contre 1
    res_majority = await engine.vote(
        question="Quelle architecture choisir ?",
        options=["Option A", "Option B"],
        voter_skills=[voter_a, voter_b, voter_c],
        voter_names=["node_a", "node_b", "node_c"],
    )
    assert res_majority.decision == "Option A"
    assert res_majority.agreement_ratio == round(2 / 3, 3)
    assert res_majority.tally["Option A"] == 2.0
    assert res_majority.tally["Option B"] == 1.0
    
    # Vote pondéré : Le vote de node_b a un poids de 5.0 -> Option B gagne
    res_weighted = await engine.vote(
        question="Quelle architecture choisir ?",
        options=["Option A", "Option B"],
        voter_skills=[voter_a, voter_b, voter_c],
        weights={"node_b": 5.0},
        voter_names=["node_a", "node_b", "node_c"],
    )
    assert res_weighted.decision == "Option B"
    assert res_weighted.tally["Option B"] == 5.0
    assert res_weighted.tally["Option A"] == 2.0


async def test_multiagent_debate_and_synthesis():
    print("\n== Test MultiAgentConsensus: Débat contradictoire et synthèse ==")
    engine = MultiAgentConsensus()
    
    async def agent_security(p: dict):
        return {"response": "Recommandation: Chiffrement E2EE obligatoire sur tous les nœuds."}
    
    async def agent_performance(p: dict):
        return {"response": "Recommandation: Privilégier le streaming continu et le cache Metal."}
    
    async def agent_moderator(p: dict):
        return {"response": "Synthèse: Nous combinons le chiffrement E2EE avec le streaming Metal pour allier sécurité et performance."}
    
    res_debate = await engine.debate_and_synthesize(
        topic="Optimisation du protocole de communication",
        debaters=[("SecurityExpert", agent_security), ("PerformanceExpert", agent_performance)],
        moderator=("LeadArchitect", agent_moderator),
    )
    
    assert res_debate.decision == "SYNTHESIS_REACHED"
    assert len(res_debate.votes) == 2
    assert "E2EE" in res_debate.synthesis
    assert "Metal" in res_debate.synthesis
