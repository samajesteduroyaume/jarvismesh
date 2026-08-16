"""
Système de gestion, registre et compétences intégrées pour JarvisMesh.

Permet de déclarer des compétences via le décorateur `@skill`, de charger
automatiquement des modules / scripts Python depuis un répertoire donné
et fournit les compétences utilitaires de base (echo, reverse, wordcount, etc.).
"""
from __future__ import annotations
import asyncio
import importlib.util
import inspect
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from pydantic import BaseModel, Field
    _HAS_PYDANTIC = True
except ImportError:
    BaseModel = object  # type: ignore
    Field = lambda *args, **kwargs: None  # type: ignore
    _HAS_PYDANTIC = False

from .mlx_engine import (
    llm,
    llm_stream,
    LLMPayload,
    MLXModelManager,
    mlx_health_extra,
    DEFAULT_MODEL_NAME,
    _HAS_MLX,
)


class SkillRegistry:
    """Registre de compétences et de leurs schémas de validation associés."""

    def __init__(self, name: str = "default"):
        self.name = name
        self._skills: dict[str, Callable] = {}
        self._schemas: dict[str, Any] = {}
        self._descriptions: dict[str, str] = {}

    def register(
        self,
        fn: Callable,
        name: Optional[str] = None,
        schema: Optional[Any] = None,
        description: Optional[str] = None,
    ) -> Callable:
        """Enregistre une fonction en tant que compétence."""
        skill_name = name or getattr(fn, "__name__", "anonymous_skill")
        self._skills[skill_name] = fn

        # Résolution du schéma (explicite ou via attributs)
        resolved_schema = schema or getattr(fn, "__skill_schema__", None)
        if resolved_schema is not None:
            self._schemas[skill_name] = resolved_schema

        # Résolution de la description (explicite ou docstring)
        desc = description or getattr(fn, "__skill_desc__", None) or (inspect.getdoc(fn) or "").strip()
        if desc:
            self._descriptions[skill_name] = desc

        # Attache les métadonnées sur la fonction elle-même
        setattr(fn, "__skill_name__", skill_name)
        setattr(fn, "__skill_schema__", resolved_schema)
        setattr(fn, "__skill_desc__", desc)
        return fn

    def register_dict(self, skills: dict[str, Callable], schemas: Optional[dict[str, Any]] = None):
        """Enregistre un dictionnaire de compétences existant."""
        schemas = schemas or {}
        for name, fn in skills.items():
            self.register(fn, name=name, schema=schemas.get(name))

    def load_file(self, file_path: str | Path) -> int:
        """Charge un fichier Python et enregistre toutes les compétences décorées avec @skill."""
        path = Path(file_path).resolve()
        if not path.is_file() or path.suffix != ".py":
            return 0

        module_name = f"jarvismesh_custom_{path.stem}_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, str(path))
        if spec is None or spec.loader is None:
            return 0

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        count = 0
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if callable(attr) and hasattr(attr, "__is_jarvismesh_skill__"):
                skill_name = getattr(attr, "__skill_name__", attr_name)
                schema = getattr(attr, "__skill_schema__", None)
                desc = getattr(attr, "__skill_desc__", None)
                self.register(attr, name=skill_name, schema=schema, description=desc)
                count += 1
        return count

    def load_from_directory(self, dir_path: str | Path, recursive: bool = True) -> int:
        """Parcourt un dossier et charge automatiquement tous les scripts Python contenant des compétences."""
        root = Path(dir_path).resolve()
        if not root.is_dir():
            return 0

        total_loaded = 0
        pattern = "**/*.py" if recursive else "*.py"
        for py_file in root.glob(pattern):
            if py_file.name.startswith((".", "_")):
                continue
            total_loaded += self.load_file(py_file)
        return total_loaded

    def get(self, name: str, default: Optional[Callable] = None) -> Optional[Callable]:
        """Récupère une compétence par son nom."""
        return self._skills.get(name, default)

    @property
    def skills(self) -> dict[str, Callable]:
        return dict(self._skills)

    @property
    def schemas(self) -> dict[str, Any]:
        return dict(self._schemas)

    @property
    def descriptions(self) -> dict[str, str]:
        return dict(self._descriptions)

    def describe(self) -> dict[str, dict[str, Any]]:
        """Retourne une description détaillée de toutes les compétences enregistrées."""
        result = {}
        for name, fn in self._skills.items():
            result[name] = {
                "description": self._descriptions.get(name, ""),
                "has_schema": name in self._schemas,
                "is_async": inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn),
                "is_stream": inspect.isgeneratorfunction(fn) or inspect.isasyncgenfunction(fn),
            }
        return result


# Registre global par défaut
default_registry = SkillRegistry("global")


def skill(
    name: Optional[str] = None,
    schema: Optional[Any] = None,
    description: Optional[str] = None,
    registry: Optional[SkillRegistry] = None,
) -> Callable:
    """Décorateur pour transformer une fonction en compétence JarvisMesh."""
    def decorator(fn: Callable) -> Callable:
        target_registry = registry or default_registry
        setattr(fn, "__is_jarvismesh_skill__", True)
        setattr(fn, "__skill_name__", name or fn.__name__)
        setattr(fn, "__skill_schema__", schema)
        setattr(fn, "__skill_desc__", description or (inspect.getdoc(fn) or "").strip())
        target_registry.register(fn, name=name, schema=schema, description=description)
        return fn

    return decorator


# ---------------------------------------------------------------------- #
# Schémas de validation Pydantic intégrés
# ---------------------------------------------------------------------- #
if _HAS_PYDANTIC:
    class ReversePayload(BaseModel):
        text: str = Field(min_length=1, max_length=10_000)

    DEFAULT_SCHEMAS = {
        "reverse": ReversePayload,
        "llm": LLMPayload,
        "llm-stream": LLMPayload,
    }
else:
    DEFAULT_SCHEMAS = {}


# ---------------------------------------------------------------------- #
# Compétences intégrées par défaut
# ---------------------------------------------------------------------- #
def echo(payload: dict) -> dict:
    """Renvoie le texte reçu tel quel."""
    return {"echo": payload.get("text", "")}


def reverse(payload: dict) -> dict:
    """Inverse la chaîne de caractères fournie."""
    text = payload.get("text", "")
    return {"reversed": text[::-1]}


def wordcount(payload: dict) -> dict:
    """Compte le nombre de mots et de caractères."""
    text = payload.get("text", "")
    return {"words": len(text.split()), "chars": len(text)}


async def slow_echo(payload: dict) -> dict:
    """Echo avec délai simulé pour tester le multiplexage asynchrone."""
    await asyncio.sleep(payload.get("delay", 1.0))
    return {"echo": payload.get("text", ""), "delay": payload.get("delay", 1.0)}


BUILTIN_SKILLS = {
    "echo": echo,
    "reverse": reverse,
    "wordcount": wordcount,
    "llm": llm,
    "llm-stream": llm_stream,
    "slow-echo": slow_echo,
}

# Alias standard
DEFAULT_SKILLS = BUILTIN_SKILLS
