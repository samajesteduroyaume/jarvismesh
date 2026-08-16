"""
Module de Contrôle d'Accès Basé sur les Rôles (RBAC) pour JarvisMesh.

Garantit que seuls les agents ou clés autorisés peuvent invoquer certaines compétences
sensibles (ex: exécution système, écriture mémoire, administration de cluster).
"""
from __future__ import annotations
import fnmatch
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


DEFAULT_ROLES: dict[str, list[str]] = {
    "admin": ["*"],
    "worker": [
        "skills:execute:llm*",
        "skills:execute:echo*",
        "skills:execute:reverse*",
        "skills:execute:rag*",
        "skills:execute:memory*",
        "skills:execute:graph*",
    ],
    "analyst": [
        "skills:execute:rag_search",
        "skills:execute:memory_search",
        "skills:execute:memory_recall",
        "skills:execute:graph_query*",
        "skills:execute:graph_find*",
    ],
    "guest": [
        "skills:execute:echo",
        "skills:execute:ping",
    ],
}


class RBACManager:
    """Gestionnaire de permissions et politiques RBAC pour le maillage."""

    def __init__(self, default_role: str = "worker"):
        self.default_role = default_role
        self.role_permissions: dict[str, set[str]] = {
            r: set(perms) for r, perms in DEFAULT_ROLES.items()
        }
        # Mapping identité (nom de nœud ou clé publique hex) -> rôle
        self.identities: dict[str, str] = {}

    def define_role(self, role_name: str, permissions: list[str]):
        """Définit ou met à jour un rôle avec sa liste de permissions."""
        self.role_permissions[role_name.lower()] = set(permissions)

    def assign_role(self, identity: str, role_name: str):
        """Assigne un rôle à un nœud ou une clé d'agent."""
        role = role_name.lower()
        if role not in self.role_permissions:
            raise ValueError(f"Rôle inconnu '{role}'. Rôles disponibles: {list(self.role_permissions.keys())}")
        self.identities[identity] = role

    def get_role(self, identity: str) -> str:
        """Retourne le rôle d'une identité (ou default_role)."""
        return self.identities.get(identity, self.default_role)

    def has_permission(self, identity: str, permission: str) -> bool:
        """Vérifie si une identité possède une permission spécifique (supporte les wildcards *)."""
        role = self.get_role(identity)
        perms = self.role_permissions.get(role, set())

        for p in perms:
            if p == "*" or fnmatch.fnmatch(permission, p):
                return True
        return False

    def authorize_skill(self, identity: str, skill_name: str) -> tuple[bool, Optional[str]]:
        """Valide si l'identité a le droit d'invoquer la compétence demandée."""
        target_perm = f"skills:execute:{skill_name}"
        if self.has_permission(identity, target_perm):
            return True, None

        role = self.get_role(identity)
        return False, f"PERMISSION_DENIED: L'identité '{identity}' (rôle: '{role}') n'est pas autorisée à exécuter '{skill_name}'."
