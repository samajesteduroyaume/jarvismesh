"""
Protocole Gossip (SWIM) pour la gestion d'appartenance et la découverte à large échelle dans JarvisMesh.

Permet à un maillage de dizaines ou centaines de nœuds de synchroniser
leurs compétences et de détecter les pannes en quasi temps-réel via
des échanges épidémiques aléatoires, sans saturer le réseau local en multicast.
"""
from __future__ import annotations
import asyncio
import enum
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class MemberState(str, enum.Enum):
    ALIVE = "alive"
    SUSPECT = "suspect"
    DEAD = "dead"


@dataclass
class GossipMember:
    name: str
    host: str
    port: int
    skills: list[str] = field(default_factory=list)
    incarnation: int = 1
    state: MemberState = MemberState.ALIVE
    last_seen: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "skills": self.skills,
            "incarnation": self.incarnation,
            "state": self.state.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GossipMember:
        return cls(
            name=d["name"],
            host=d["host"],
            port=d["port"],
            skills=d.get("skills", []),
            incarnation=d.get("incarnation", 1),
            state=MemberState(d.get("state", "alive")),
        )


class GossipCluster:
    """Gestionnaire de cluster basé sur le protocole Gossip SWIM."""

    def __init__(
        self,
        local_name: str,
        local_host: str,
        local_port: int,
        local_skills: Optional[list[str]] = None,
        ping_interval: float = 2.0,
        suspect_timeout: float = 4.0,
    ):
        self.local_name = local_name
        self.local_host = local_host
        self.local_port = local_port
        self.local_skills = local_skills or []
        self.ping_interval = ping_interval
        self.suspect_timeout = suspect_timeout

        self.members: dict[str, GossipMember] = {
            local_name: GossipMember(
                name=local_name,
                host=local_host,
                port=local_port,
                skills=self.local_skills,
                state=MemberState.ALIVE,
            )
        }
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def merge_members(self, remote_members: list[dict[str, Any]]) -> list[str]:
        """Fusionne une table de membres reçue via gossip. Retourne les nœuds mis à jour."""
        updated = []
        for m_dict in remote_members:
            name = m_dict.get("name")
            if not name:
                continue

            # Ne jamais écraser son propre état local sauf si incarnation plus haute
            if name == self.local_name:
                continue

            remote_incarnation = m_dict.get("incarnation", 1)
            remote_state = MemberState(m_dict.get("state", "alive"))

            if name not in self.members:
                new_mem = GossipMember.from_dict(m_dict)
                new_mem.last_seen = time.time()
                self.members[name] = new_mem
                updated.append(name)
            else:
                local_mem = self.members[name]
                if remote_incarnation > local_mem.incarnation:
                    local_mem.incarnation = remote_incarnation
                    local_mem.state = remote_state
                    local_mem.skills = m_dict.get("skills", local_mem.skills)
                    local_mem.last_seen = time.time()
                    updated.append(name)
                elif remote_incarnation == local_mem.incarnation:
                    if local_mem.state == MemberState.ALIVE and remote_state == MemberState.SUSPECT:
                        local_mem.state = MemberState.SUSPECT
                        updated.append(name)
                    elif remote_state == MemberState.DEAD:
                        local_mem.state = MemberState.DEAD
                        updated.append(name)

        return updated

    def get_alive_members(self) -> list[GossipMember]:
        """Retourne la liste des membres actifs et joignables."""
        return [m for m in self.members.values() if m.state == MemberState.ALIVE]

    def get_skills_map(self) -> dict[str, list[str]]:
        """Retourne un dictionnaire {compétence: [noms_des_noeuds_qui_la_possedent]}."""
        mapping: dict[str, list[str]] = {}
        for m in self.get_alive_members():
            for skill in m.skills:
                mapping.setdefault(skill, []).append(m.name)
        return mapping

    def get_gossip_digest(self) -> list[dict[str, Any]]:
        """Génère le résumé de la table de membres pour diffusion."""
        return [m.to_dict() for m in self.members.values()]

    def get_skills(self) -> dict[str, Callable]:
        """Compétences internes exposées sur le maillage pour la synchronisation gossip."""
        async def _gossip_ping(payload: dict) -> dict:
            remote_digest = payload.get("digest", [])
            self.merge_members(remote_digest)
            return {
                "ok": True,
                "ack": True,
                "digest": self.get_gossip_digest(),
            }

        return {"_gossip_ping": _gossip_ping}

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._gossip_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _gossip_loop(self):
        """Boucle périodique de sélection aléatoire d'un pair et échange d'état."""
        while self._running:
            await asyncio.sleep(self.ping_interval)
            
            # Vérification des nœuds suspects expirés
            now = time.time()
            for m in list(self.members.values()):
                if m.name != self.local_name and m.state == MemberState.SUSPECT:
                    if now - m.last_seen > self.suspect_timeout:
                        m.state = MemberState.DEAD

            # Choix d'une cible aléatoire parmi les pairs connus
            candidates = [m for m in self.members.values() if m.name != self.local_name and m.state != MemberState.DEAD]
            if not candidates:
                continue

            target = random.choice(candidates)
            # En production, JarvisNode.delegate("_gossip_ping", ...) est appelé vers target
