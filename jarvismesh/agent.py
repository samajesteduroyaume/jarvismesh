"""
Module d'Agent Autonome ReAct & Function Calling Distribué pour JarvisMesh.

Permet à un agent de recevoir un objectif en langage naturel, d'introspecter
l'ensemble des compétences disponibles sur le maillage, d'élaborer une chaîne
de raisonnement récursive (Thought -> Action -> Observation -> Final Answer)
et de s'auto-réparer en cas d'erreur.
"""
from __future__ import annotations
import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .node import JarvisNode


@dataclass
class AgentStep:
    """Représente une étape de raisonnement et d'action de l'agent."""
    step_number: int
    thought: str = ""
    action_skill: Optional[str] = None
    action_payload: dict[str, Any] = field(default_factory=dict)
    observation: Any = None
    handled_by: Optional[str] = None
    duration_sec: float = 0.0
    error: Optional[str] = None


@dataclass
class AgentTrace:
    """Trace complète d'exécution d'un objectif autonome."""
    objective: str
    steps: list[AgentStep] = field(default_factory=list)
    final_answer: str = ""
    ok: bool = False
    total_duration_sec: float = 0.0
    error: Optional[str] = None


class AutonomousAgent:
    """Agent autonome ReAct avec planification dynamique et appel d'outils distribués."""

    def __init__(
        self,
        node: JarvisNode,
        max_steps: int = 8,
        temperature: float = 0.2,
        model: Optional[str] = None,
        llm_skill: str = "llm",
    ):
        self.node = node
        self.max_steps = max_steps
        self.temperature = temperature
        self.model = model
        self.llm_skill = llm_skill

    async def _get_available_mesh_skills(self) -> dict[str, Any]:
        """Collecte la liste et description des compétences disponibles sur tout le maillage."""
        available = {}
        for s_name in self.node.skills.keys():
            if not s_name.startswith("_"):
                available[s_name] = f"Disponible localement sur '{self.node.name}'"

        for p_name, p_info in self.node.peers.items():
            for s_name in p_info.get("skills", []):
                if not s_name.startswith("_"):
                    available[s_name] = f"Disponible sur le pair '{p_name}'"

        return available

    def _build_system_prompt(self, skills_desc: dict[str, str]) -> str:
        tools_list = "\n".join([f"- `{k}` : {v}" for k, v in skills_desc.items()])
        return (
            "Tu es un Agent IA Autonome opérant sur le réseau décentralisé JarvisMesh.\n"
            "Ton rôle est d'accomplir l'objectif fixé en utilisant les compétences disponibles sur le maillage.\n\n"
            "COMPÉTENCES DU MAILLAGE DISPONIBLES :\n"
            f"{tools_list}\n\n"
            "FORMAT DE RAISONNEMENT REQUIS (ReAct) :\n"
            "Pour chaque étape, tu dois TOUJOURS répondre selon ce format strict :\n"
            "Thought: <Ton analyse de la situation et ce que tu souhaites faire>\n"
            "Action: {\"skill\": \"nom_de_la_competence\", \"payload\": {\"param\": \"valeur\"}}\n\n"
            "Quand tu as toutes les informations pour répondre à l'objectif final :\n"
            "Thought: <Ton analyse finale>\n"
            "Final Answer: <Ta réponse complète et claire à l'objectif>\n"
        )

    def _parse_llm_response(self, text: str) -> tuple[str, Optional[dict], Optional[str]]:
        """Extrait Thought, Action et Final Answer depuis la sortie du LLM de manière robuste."""
        thought = ""
        action_dict = None
        final_answer = None

        # 1. Cas Final Answer
        if "Final Answer:" in text:
            parts = text.split("Final Answer:", 1)
            if "Thought:" in parts[0]:
                thought = parts[0].split("Thought:", 1)[1].strip()
            else:
                thought = parts[0].strip()
            final_answer = parts[1].strip()
            return thought, None, final_answer

        # 2. Cas Action JSON
        if "Action:" in text:
            parts = text.split("Action:", 1)
            if "Thought:" in parts[0]:
                thought = parts[0].split("Thought:", 1)[1].strip()
            else:
                thought = parts[0].strip()
            action_raw = parts[1].strip()

            start_idx = action_raw.find("{")
            end_idx = action_raw.rfind("}")
            if start_idx != -1 and end_idx != -1 and end_idx >= start_idx:
                json_str = action_raw[start_idx : end_idx + 1]
                try:
                    action_dict = json.loads(json_str)
                except Exception:
                    try:
                        action_dict = json.loads(json_str.replace("'", '"'))
                    except Exception:
                        pass
            return thought, action_dict, None

        # 3. Fallback
        if "Thought:" in text:
            thought = text.split("Thought:", 1)[1].strip()
        else:
            thought = text.strip()
        return thought, None, None

    async def run(
        self,
        objective: str,
        on_step: Optional[Callable[[AgentStep], None]] = None,
    ) -> AgentTrace:
        """Lance la boucle autonome ReAct pour accomplir l'objectif."""
        start_time = time.time()
        trace = AgentTrace(objective=objective)

        mesh_skills = await self._get_available_mesh_skills()
        system_prompt = self._build_system_prompt(mesh_skills)

        conversation_history = f"OBJECTIF : {objective}\n"

        for step_idx in range(1, self.max_steps + 1):
            step_start = time.time()
            current_step = AgentStep(step_number=step_idx)

            prompt = (
                f"{system_prompt}\n\n"
                f"HISTORIQUE D'EXÉCUTION :\n{conversation_history}\n\n"
                f"Étape {step_idx} — Quel est ton prochain Thought et Action ?"
            )

            # Appel du LLM
            llm_payload = {
                "prompt": prompt,
                "temperature": self.temperature,
                "max_tokens": 512,
            }
            if self.model:
                llm_payload["model"] = self.model

            try:
                llm_resp = await self.node.delegate(self.llm_skill, llm_payload)
                if not llm_resp.ok:
                    raise RuntimeError(f"Erreur d'inférence LLM: {llm_resp.error}")
                llm_text = llm_resp.result.get("response", "").strip()
            except Exception as e:
                current_step.error = f"Échec d'appel LLM: {e}"
                current_step.duration_sec = time.time() - step_start
                trace.steps.append(current_step)
                trace.error = current_step.error
                break

            thought, action, final_answer = self._parse_llm_response(llm_text)
            current_step.thought = thought

            # Cas 1 : Réponse finale atteinte
            if final_answer:
                current_step.duration_sec = time.time() - step_start
                trace.steps.append(current_step)
                trace.final_answer = final_answer
                trace.ok = True
                if on_step:
                    on_step(current_step)
                break

            # Cas 2 : Une action d'outil doit être exécutée
            if action and isinstance(action, dict) and "skill" in action:
                skill_name = action.get("skill")
                payload = action.get("payload", {})
                current_step.action_skill = skill_name
                current_step.action_payload = payload

                try:
                    # Exécution distribuée via le maillage
                    resp = await self.node.delegate(skill_name, payload)
                    current_step.handled_by = resp.handled_by
                    if resp.ok:
                        current_step.observation = resp.result
                        obs_str = json.dumps(resp.result, ensure_ascii=False)
                    else:
                        current_step.observation = f"Erreur: {resp.error}"
                        current_step.error = resp.error
                        obs_str = f"ERREUR lors de l'exécution de '{skill_name}': {resp.error}"
                except Exception as e:
                    current_step.observation = f"Exception: {e}"
                    current_step.error = str(e)
                    obs_str = f"EXCEPTION: {e}"

                # Mise à jour de l'historique de la boucle
                conversation_history += (
                    f"\nThought: {thought}\n"
                    f"Action: {json.dumps(action)}\n"
                    f"Observation: {obs_str}\n"
                )
            else:
                # Fallback si le format n'a pas été respecté
                current_step.observation = "Erreur de syntaxe : format 'Action: {...}' ou 'Final Answer: ...' attendu."
                conversation_history += f"\nThought: {thought}\nObservation: {current_step.observation}\n"

            current_step.duration_sec = time.time() - step_start
            trace.steps.append(current_step)
            if on_step:
                on_step(current_step)

        trace.total_duration_sec = time.time() - start_time
        if not trace.final_answer and not trace.error:
            trace.error = f"Nombre maximal d'étapes ({self.max_steps}) atteint sans conclusion."

        return trace
