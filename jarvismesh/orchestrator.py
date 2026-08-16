"""
Orchestrateur & Chaînage de tâches multi-agents pour JarvisMesh.

Permet de définir et d'exécuter des workflows / pipelines complexes combinant
plusieurs compétences réparties sur différents nœuds du maillage, de manière
séquentielle ou parallèle, avec propagation automatique du contexte.
"""
from __future__ import annotations
import asyncio
import inspect
import json
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional, Union

from .node import JarvisNode
from .protocol import TaskResponse


@dataclass
class WorkflowStep:
    name: str
    skill: str
    payload: Union[dict, Callable[[dict], dict], str] = field(default_factory=dict)
    target_peer: Optional[str] = None
    stream: bool = False
    timeout: float = 30.0
    on_error: str = "abort"  # "abort" ou "continue"
    retries: int = 0

    def to_dict(self) -> dict:
        p = self.payload if not callable(self.payload) else "<function>"
        return {
            "name": self.name,
            "skill": self.skill,
            "payload": p,
            "target_peer": self.target_peer,
            "stream": self.stream,
            "timeout": self.timeout,
            "on_error": self.on_error,
            "retries": self.retries,
        }


@dataclass
class StepExecutionResult:
    step_name: str
    skill: str
    ok: bool
    handled_by: str = ""
    result: Any = None
    error: Optional[str] = None
    duration_sec: float = 0.0
    retries_used: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class WorkflowResult:
    workflow_name: str
    ok: bool
    duration_sec: float
    step_results: dict[str, StepExecutionResult] = field(default_factory=dict)
    final_output: Any = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "workflow_name": self.workflow_name,
            "ok": self.ok,
            "duration_sec": round(self.duration_sec, 3),
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "final_output": self.final_output,
            "errors": self.errors,
        }


def _resolve_context_value(template: str, context: dict) -> Any:
    """Résout des expressions comme '{steps.step1.result.text}' ou '{input.query}'."""
    pattern = re.compile(r"\{([a-zA-Z0-9_.]+)\}")
    matches = pattern.findall(template)
    if not matches:
        return template

    # Si le template est exactement "{expression}", on retourne la valeur typée directe
    if template.strip() == f"{{{matches[0]}}}":
        return _extract_path(context, matches[0])

    # Sinon substitution dans la chaîne
    result_str = template
    for path in matches:
        val = _extract_path(context, path)
        result_str = result_str.replace(f"{{{path}}}", str(val if val is not None else ""))
    return result_str


def _extract_path(data: Any, path: str) -> Any:
    """Navigue dans un dictionnaire/objet via un chemin en notation pointée."""
    parts = path.split(".")
    current = data
    for p in parts:
        if isinstance(current, dict):
            current = current.get(p)
        elif hasattr(current, p):
            current = getattr(current, p)
        else:
            return None
    return current


def _interpolate_payload(payload_obj: Any, context: dict) -> Any:
    """Interpole récursivement les variables de contexte dans un payload."""
    if callable(payload_obj):
        return payload_obj(context)
    if isinstance(payload_obj, str):
        return _resolve_context_value(payload_obj, context)
    if isinstance(payload_obj, dict):
        return {k: _interpolate_payload(v, context) for k, v in payload_obj.items()}
    if isinstance(payload_obj, list):
        return [_interpolate_payload(item, context) for item in payload_obj]
    return payload_obj


class Workflow:
    """Représente un workflow / pipeline multi-agents réutilisable."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        # Chaque élément est soit un WorkflowStep (séquentiel), soit une liste de WorkflowStep (parallèle)
        self.stages: list[Union[WorkflowStep, list[WorkflowStep]]] = []

    def add_step(
        self,
        name: str,
        skill: str,
        payload: Union[dict, Callable[[dict], dict], str] = None,
        target_peer: Optional[str] = None,
        stream: bool = False,
        timeout: float = 30.0,
        on_error: str = "abort",
        retries: int = 0,
    ) -> Workflow:
        """Ajoute une étape séquentielle."""
        step = WorkflowStep(
            name=name,
            skill=skill,
            payload=payload if payload is not None else {},
            target_peer=target_peer,
            stream=stream,
            timeout=timeout,
            on_error=on_error,
            retries=retries,
        )
        self.stages.append(step)
        return self

    def add_parallel_steps(self, steps: list[WorkflowStep]) -> Workflow:
        """Ajoute un groupe d'étapes à exécuter en parallèle."""
        if steps:
            self.stages.append(list(steps))
        return self

    async def _execute_single_step(
        self,
        node: JarvisNode,
        step: WorkflowStep,
        context: dict,
        on_progress: Optional[Callable[[str, str, Any], None]] = None,
    ) -> StepExecutionResult:
        """Exécute une seule étape avec interpolation de contexte et retries."""
        resolved_payload = _interpolate_payload(step.payload, context)
        if not isinstance(resolved_payload, dict):
            resolved_payload = {"input": resolved_payload}

        if on_progress:
            on_progress("step_start", step.name, {"skill": step.skill, "payload": resolved_payload})

        attempts = 0
        max_attempts = step.retries + 1
        last_error = None
        resp: Optional[TaskResponse] = None
        t0 = time.monotonic()

        while attempts < max_attempts:
            attempts += 1
            try:
                if step.stream:
                    chunks = []
                    def handle_chunk(c):
                        chunks.append(c)
                        if on_progress:
                            on_progress("step_chunk", step.name, {"chunk": c})

                    resp = await node.delegate_stream(
                        skill=step.skill,
                        payload=resolved_payload,
                        on_chunk=handle_chunk,
                        peer_name=step.target_peer,
                        timeout=step.timeout,
                    )
                else:
                    resp = await node.delegate(
                        skill=step.skill,
                        payload=resolved_payload,
                        peer_name=step.target_peer,
                        timeout=step.timeout,
                    )

                if resp.ok:
                    duration = time.monotonic() - t0
                    step_res = StepExecutionResult(
                        step_name=step.name,
                        skill=step.skill,
                        ok=True,
                        handled_by=resp.handled_by,
                        result=resp.result,
                        duration_sec=duration,
                        retries_used=attempts - 1,
                    )
                    if on_progress:
                        on_progress("step_done", step.name, step_res.to_dict())
                    return step_res
                else:
                    last_error = resp.error
            except Exception as e:
                last_error = str(e)

            if attempts < max_attempts:
                await asyncio.sleep(0.5)

        duration = time.monotonic() - t0
        step_res = StepExecutionResult(
            step_name=step.name,
            skill=step.skill,
            ok=False,
            handled_by=resp.handled_by if resp else "",
            error=last_error or "Échec de l'étape",
            duration_sec=duration,
            retries_used=attempts - 1,
        )
        if on_progress:
            on_progress("step_error", step.name, step_res.to_dict())
        return step_res

    async def run(
        self,
        node: JarvisNode,
        initial_input: Optional[dict] = None,
        on_progress: Optional[Callable[[str, str, Any], None]] = None,
    ) -> WorkflowResult:
        """Exécute l'intégralité du workflow."""
        start_time = time.monotonic()
        context: dict[str, Any] = {
            "input": initial_input or {},
            "steps": {},
        }
        step_results: dict[str, StepExecutionResult] = {}
        errors: list[str] = []
        last_result: Any = None
        workflow_ok = True

        for stage in self.stages:
            if isinstance(stage, WorkflowStep):
                # Étape séquentielle
                res = await self._execute_single_step(node, stage, context, on_progress)
                step_results[stage.name] = res
                context["steps"][stage.name] = {
                    "ok": res.ok,
                    "result": res.result,
                    "error": res.error,
                    "handled_by": res.handled_by,
                }
                last_result = res.result
                if not res.ok:
                    errors.append(f"Étape '{stage.name}' ({stage.skill}) a échoué: {res.error}")
                    if stage.on_error == "abort":
                        workflow_ok = False
                        break
            elif isinstance(stage, list):
                # Groupe d'étapes en parallèle
                tasks = [self._execute_single_step(node, s, context, on_progress) for s in stage]
                parallel_results = await asyncio.gather(*tasks, return_exceptions=False)
                for s, res in zip(stage, parallel_results):
                    step_results[s.name] = res
                    context["steps"][s.name] = {
                        "ok": res.ok,
                        "result": res.result,
                        "error": res.error,
                        "handled_by": res.handled_by,
                    }
                    if not res.ok:
                        errors.append(f"Étape parallèle '{s.name}' ({s.skill}) a échoué: {res.error}")
                        if s.on_error == "abort":
                            workflow_ok = False
                last_result = {s.name: r.result for s, r in zip(stage, parallel_results) if r.ok}
                if not workflow_ok:
                    break

        total_duration = time.monotonic() - start_time
        return WorkflowResult(
            workflow_name=self.name,
            ok=workflow_ok and len(errors) == 0,
            duration_sec=total_duration,
            step_results=step_results,
            final_output=last_result,
            errors=errors,
        )

    def to_dict(self) -> dict:
        stages_data = []
        for stage in self.stages:
            if isinstance(stage, WorkflowStep):
                stages_data.append(stage.to_dict())
            elif isinstance(stage, list):
                stages_data.append([s.to_dict() for s in stage])
        return {
            "name": self.name,
            "description": self.description,
            "stages": stages_data,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Workflow:
        wf = cls(name=data.get("name", "unnamed_workflow"), description=data.get("description", ""))
        for stage_item in data.get("stages", []):
            if isinstance(stage_item, dict):
                wf.stages.append(WorkflowStep(**stage_item))
            elif isinstance(stage_item, list):
                wf.stages.append([WorkflowStep(**s) for s in stage_item])
        return wf

    @classmethod
    def from_json(cls, json_str: str) -> Workflow:
        return cls.from_dict(json.loads(json_str))
