"""
Protocole JarvisMesh — messages échangés entre agents.

Format JSON minimal, inspiré de MCP mais pensé pour du pair-à-pair local
(pas de client/serveur central, chaque noeud est agent ET fournisseur).

Authentification : chaque TaskRequest peut porter une signature HMAC-SHA256
calculée sur (request_id|origin|skill|ts|payload_json) avec une clé
pré-partagée (PSK). Un noeud configuré avec un `psk` refuse toute requête
non signée ou mal signée. Sans `psk`, le comportement est inchangé
(rétro-compatible) : c'est le mode "réseau de confiance" historique.
"""
from __future__ import annotations
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

PROTOCOL_VERSION = "1.0"
SERVICE_TYPE = "_jarvismesh._tcp.local."

# Compétences internes réservées, présentes sur tout noeud sans avoir à
# être déclarées dans `skills`. Utilisées par l'introspection et le
# routage par charge (voir node.py).
DESCRIBE_SKILL = "_describe_skills"
HEALTH_SKILL = "_health"
RESERVED_SKILLS = {DESCRIBE_SKILL, HEALTH_SKILL}


def _signing_base(request_id: str, origin: str, skill: str, ts: float, payload: dict) -> bytes:
    # json.dumps avec sort_keys : la base signée est déterministe même si
    # le payload contient des dicts dans un ordre différent d'un bout à
    # l'autre (sérialisation/désérialisation).
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    base = f"{request_id}|{origin}|{skill}|{ts!r}|{payload_json}"
    return base.encode("utf-8")


def sign_request(psk: str, request_id: str, origin: str, skill: str, ts: float, payload: dict) -> str:
    """Calcule le HMAC-SHA256 hex d'une requête pour une clé pré-partagée."""
    mac = hmac.new(psk.encode("utf-8"), _signing_base(request_id, origin, skill, ts, payload),
                    hashlib.sha256)
    return mac.hexdigest()


def verify_request(psk: str, request_id: str, origin: str, skill: str, ts: float,
                    payload: dict, signature: Optional[str]) -> bool:
    """Vérifie la signature d'une requête en temps constant. Retourne False
    si aucune signature n'est fournie alors qu'un psk est exigé."""
    if not signature:
        return False
    expected = sign_request(psk, request_id, origin, skill, ts, payload)
    return hmac.compare_digest(expected, signature)


@dataclass
class TaskRequest:
    skill: str
    payload: dict
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    origin: str = ""
    ts: float = field(default_factory=time.time)
    type: str = "task_request"
    # Signature hex (HMAC-SHA256 ou Ed25519)
    sig: Optional[str] = None
    # Clé publique de l'émetteur (hex) si auth Ed25519
    pubkey: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    def sign(self, psk: str) -> None:
        self.sig = sign_request(psk, self.request_id, self.origin, self.skill, self.ts, self.payload)

    def verify(self, psk: str) -> bool:
        return verify_request(psk, self.request_id, self.origin, self.skill, self.ts, self.payload, self.sig)

    def sign_ed25519(self, identity: Any) -> None:
        self.pubkey = identity.public_key_hex
        self.sig = identity.sign(self.request_id, self.origin, self.skill, self.ts, self.payload)


@dataclass
class TaskChunk:
    request_id: str
    index: int
    chunk: Any
    type: str = "task_chunk"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


@dataclass
class TaskResponse:
    request_id: str
    ok: bool
    result: Any = None
    error: Optional[str] = None
    handled_by: str = ""
    streamed: bool = False
    type: str = "task_response"

    def to_json(self) -> str:
        return json.dumps(asdict(self))


def parse_message(raw: str) -> dict:
    return json.loads(raw)
