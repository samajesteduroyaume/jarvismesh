"""
Sous-package de gestion des compétences (Skills) pour JarvisMesh.
"""
from .registry import (
    SkillRegistry,
    default_registry,
    skill,
    BUILTIN_SKILLS,
    DEFAULT_SKILLS,
    DEFAULT_SCHEMAS,
    echo,
    reverse,
    wordcount,
    slow_echo,
)

__all__ = [
    "SkillRegistry",
    "default_registry",
    "skill",
    "BUILTIN_SKILLS",
    "DEFAULT_SKILLS",
    "DEFAULT_SCHEMAS",
    "echo",
    "reverse",
    "wordcount",
    "slow_echo",
]
