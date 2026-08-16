"""
Module de Sandbox Sécurisée et Auto-Programmation de Compétences pour JarvisMesh.

Permet aux agents d'exécuter du code Python dans un environnement hermétique et
de générer / déployer de nouvelles compétences (@skill) à chaud sans redémarrage.
"""
from __future__ import annotations
import ast
import asyncio
import inspect
import json
import math
import re
import time
from typing import Any, Callable, Dict, Optional, Tuple

from ..skills.registry import SkillRegistry, default_registry


# Modules et fonctions sûrs autorisés dans la sandbox
SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bin": bin,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "hex": hex,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "range": range,
    "reversed": reversed,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
    "math": math,
    "json": json,
    "re": re,
    "time": time,
}

FORBIDDEN_AST_NODES = (
    ast.Import,
    ast.ImportFrom,
)

FORBIDDEN_NAMES = {
    "__import__",
    "eval",
    "exec",
    "open",
    "globals",
    "locals",
    "vars",
    "compile",
    "getattr",
    "setattr",
    "delattr",
}


class SandboxSkillExecutor:
    """Exécuteur de code Python sécurisé avec validation syntaxique AST."""

    @staticmethod
    def validate_code_safety(code: str) -> tuple[bool, Optional[str]]:
        """Vérifie qu'aucun import non autorisé ou appel dangereux n'est présent."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"Erreur de syntaxe Python : {e}"

        for node in ast.walk(tree):
            if isinstance(node, FORBIDDEN_AST_NODES):
                return False, "Les instructions 'import' et 'from ... import' sont interdites dans la sandbox."
            if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                return False, f"L'utilisation de la fonction interne '{node.id}' est strictement interdite."

        return True, None

    @staticmethod
    def execute_snippet(code: str, context: Optional[dict[str, Any]] = None, timeout_sec: float = 3.0) -> dict[str, Any]:
        """Exécute un extrait de code dans un environnement restreint."""
        safe, err = SandboxSkillExecutor.validate_code_safety(code)
        if not safe:
            return {"ok": False, "error": err}

        local_vars: dict[str, Any] = dict(context or {})
        global_vars = {"__builtins__": SAFE_BUILTINS, "math": math, "json": json, "re": re}

        start_t = time.time()
        try:
            # Exécution dans le namespace sécurisé
            exec(code, global_vars, local_vars)
            duration = time.time() - start_t
            
            # Filtre les résultats sérialisables
            result_vars = {
                k: v for k, v in local_vars.items()
                if not k.startswith("_") and not inspect.isroutine(v)
            }
            return {
                "ok": True,
                "output": result_vars,
                "duration_sec": round(duration, 4),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"Erreur lors de l'exécution dans la sandbox : {e}",
                "duration_sec": round(time.time() - start_t, 4),
            }


class DynamicSkillManager:
    """Gestionnaire de création et injection à chaud de compétences sur le maillage."""

    def __init__(self, registry: Optional[SkillRegistry] = None):
        self.registry = registry or default_registry

    def register_code_skill(
        self,
        skill_name: str,
        function_code: str,
        test_payload: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Compile, valide et enregistre une nouvelle compétence @skill en temps réel."""
        # 1. Validation de sécurité
        safe, err = SandboxSkillExecutor.validate_code_safety(function_code)
        if not safe:
            return {"ok": False, "error": err}

        # 2. Compilation
        global_vars = {"__builtins__": SAFE_BUILTINS, "math": math, "json": json, "re": re}
        local_vars: dict[str, Any] = {}

        try:
            exec(function_code, global_vars, local_vars)
        except Exception as e:
            return {"ok": False, "error": f"Échec de compilation du skill : {e}"}

        # Recherche de la fonction définie
        skill_fn = None
        for k, v in local_vars.items():
            if inspect.isfunction(v):
                skill_fn = v
                break

        if not skill_fn:
            return {"ok": False, "error": "Aucune fonction trouvée dans le code fourni."}

        # 3. Test unitaire interne si payload de test fourni
        if test_payload is not None:
            try:
                test_res = skill_fn(test_payload)
                if inspect.isawaitable(test_res):
                    test_res = asyncio.run(test_res)
            except Exception as e:
                return {"ok": False, "error": f"Le test unitaire interne a échoué : {e}"}

        # 4. Enregistrement dans le registre de compétences
        self.registry.register(skill_fn, name=skill_name)

        return {
            "ok": True,
            "skill_name": skill_name,
            "registered": True,
            "total_skills": len(self.registry.skills),
        }


def get_sandbox_skills(manager: Optional[DynamicSkillManager] = None) -> dict[str, Callable]:
    """Compétences mesh pour l'exécution en sandbox et l'auto-programmation."""
    mgr = manager or DynamicSkillManager()

    async def sandbox_execute_code(payload: dict) -> dict:
        code = payload.get("code", "")
        if not code:
            return {"ok": False, "error": "Le paramètre 'code' est requis."}
        context = payload.get("context", {})
        return SandboxSkillExecutor.execute_snippet(code, context=context)

    async def skill_dynamic_register(payload: dict) -> dict:
        name = payload.get("name")
        code = payload.get("code")
        test_in = payload.get("test_payload")
        if not name or not code:
            return {"ok": False, "error": "Les paramètres 'name' et 'code' sont requis."}
        return mgr.register_code_skill(name, code, test_payload=test_in)

    return {
        "sandbox_execute_code": sandbox_execute_code,
        "skill_dynamic_register": skill_dynamic_register,
    }
