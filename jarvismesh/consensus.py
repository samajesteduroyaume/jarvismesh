"""
Module de Consensus et Débat Multi-Agents pour JarvisMesh.

Permet à plusieurs agents du maillage de voter, débattre et converger vers une décision
ou une synthèse collective sans dépendre d'un arbitre central unique.
"""
from __future__ import annotations
import asyncio
import collections
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class AgentVote:
    agent_id: str
    choice: str
    confidence: float = 1.0
    rationale: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConsensusResult:
    question: str
    strategy: str  # 'majority_vote', 'weighted_vote', 'debate_synthesis'
    decision: str
    agreement_ratio: float
    tally: dict[str, float]
    votes: list[AgentVote]
    synthesis: Optional[str] = None
    duration_sec: float = 0.0


class MultiAgentConsensus:
    """Moteur de décision collective inter-agents."""

    def __init__(self, node: Any = None):
        self.node = node

    async def vote(
        self,
        question: str,
        options: list[str],
        voter_skills: list[Callable[[dict], Any]],
        weights: Optional[dict[str, float]] = None,
        voter_names: Optional[list[str]] = None,
    ) -> ConsensusResult:
        """Collecte les votes de plusieurs agents en parallèle et calcule le résultat."""
        start_t = time.time()
        weights = weights or {}
        v_names = voter_names or [f"agent_{i+1}" for i in range(len(voter_skills))]

        prompt_tpl = (
            f"Question: {question}\n"
            f"Options valides: {', '.join(options)}\n"
            "Format requis: Réponds UNIQUEMENT avec l'option choisie suivie d'une courte justification."
        )

        async def _call_voter(idx: int, skill_fn: Callable) -> AgentVote:
            name = v_names[idx]
            try:
                res = await skill_fn({"prompt": prompt_tpl, "query": prompt_tpl})
                resp_text = res.get("response", str(res)) if isinstance(res, dict) else str(res)

                # Extraction du choix
                choice = "UNKNOWN"
                for opt in options:
                    if opt.lower() in resp_text.lower():
                        choice = opt
                        break

                return AgentVote(
                    agent_id=name,
                    choice=choice,
                    confidence=1.0,
                    rationale=resp_text.strip(),
                )
            except Exception as e:
                return AgentVote(agent_id=name, choice="ERROR", confidence=0.0, rationale=str(e))

        votes = await asyncio.gather(*[_call_voter(i, fn) for i, fn in enumerate(voter_skills)])

        # Décompte pondéré
        tally: dict[str, float] = collections.defaultdict(float)
        for v in votes:
            if v.choice not in ("UNKNOWN", "ERROR"):
                w = weights.get(v.agent_id, 1.0)
                tally[v.choice] += w * v.confidence

        total_weight = sum(tally.values())
        if tally:
            winner = max(tally.keys(), key=lambda k: tally[k])
            ratio = round(tally[winner] / total_weight, 3) if total_weight > 0 else 0.0
        else:
            winner = options[0] if options else "NO_CONSENSUS"
            ratio = 0.0

        return ConsensusResult(
            question=question,
            strategy="weighted_vote" if weights else "majority_vote",
            decision=winner,
            agreement_ratio=ratio,
            tally=dict(tally),
            votes=list(votes),
            duration_sec=round(time.time() - start_t, 3),
        )

    async def debate_and_synthesize(
        self,
        topic: str,
        debaters: list[tuple[str, Callable]],
        moderator: tuple[str, Callable],
    ) -> ConsensusResult:
        """Débat contradictoire entre pairs suivi d'une synthèse modérée."""
        start_t = time.time()
        arguments = []

        # Tour 1 : Les débatteurs exposent leurs perspectives en parallèle
        for name, fn in debaters:
            p = f"Sujet: {topic}\nExpose tes arguments, ton analyse et ta recommandation claire en tant qu'expert '{name}'."
            res = await fn({"prompt": p, "text": p})
            text = res.get("response", str(res)) if isinstance(res, dict) else str(res)
            arguments.append({"agent": name, "argument": text.strip()})

        # Tour 2 : Le modérateur arbitre et synthétise
        mod_name, mod_fn = moderator
        mod_prompt = (
            f"Sujet du débat: {topic}\n\n"
            "Arguments des différents agents :\n"
            + "\n---\n".join([f"[{a['agent']}]: {a['argument']}" for a in arguments])
            + "\n\nEn tant qu'arbitre/modérateur, synthétise les points de convergence et rends une décision finale motivée."
        )

        mod_res = await mod_fn({"prompt": mod_prompt, "text": mod_prompt})
        synth_text = mod_res.get("response", str(mod_res)) if isinstance(mod_res, dict) else str(mod_res)

        return ConsensusResult(
            question=topic,
            strategy="debate_synthesis",
            decision="SYNTHESIS_REACHED",
            agreement_ratio=1.0,
            tally={},
            votes=[AgentVote(agent_id=a["agent"], choice="ARGUMENT", rationale=a["argument"]) for a in arguments],
            synthesis=synth_text.strip(),
            duration_sec=round(time.time() - start_t, 3),
        )
