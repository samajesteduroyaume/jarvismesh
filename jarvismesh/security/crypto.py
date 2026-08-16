"""
Module de cryptographie asymétrique Ed25519 et gestion des identités pour JarvisMesh.

Permet à chaque nœud d'avoir sa propre paire de clés privée/publique (Ed25519),
de signer ses requêtes sans clé partagée et d'autoriser/révoquer des pairs de
manière granulaire via un TrustStore.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from typing import Optional, Set

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    from cryptography.exceptions import InvalidSignature
    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def _signing_base(request_id: str, origin: str, skill: str, ts: float, payload: dict, pubkey_hex: str = "") -> bytes:
    """Génère la chaîne canonique d'octets à signer."""
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    base = f"{request_id}|{origin}|{pubkey_hex}|{skill}|{ts!r}|{payload_json}"
    return base.encode("utf-8")


class NodeIdentity:
    """Représente l'identité cryptographique d'un nœud (clé privée + publique Ed25519)."""

    def __init__(self, private_key: "ed25519.Ed25519PrivateKey"):
        if not _HAS_CRYPTO:
            raise ImportError(
                "La bibliothèque 'cryptography' est requise pour l'identité Ed25519. "
                "Installez-la via `pip install cryptography` ou `pip install -e .`"
            )
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self.public_key_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key_hex = self.public_key_bytes.hex()
        self.node_id = self.public_key_hex[:16]

    @classmethod
    def generate(cls) -> NodeIdentity:
        """Génère une nouvelle identité Ed25519 aléatoire."""
        if not _HAS_CRYPTO:
            raise ImportError("cryptography n'est pas installé.")
        key = ed25519.Ed25519PrivateKey.generate()
        return cls(key)

    @classmethod
    def from_private_bytes(cls, raw_bytes: bytes) -> NodeIdentity:
        """Charge une identité depuis 32 octets de clé privée brute."""
        if not _HAS_CRYPTO:
            raise ImportError("cryptography n'est pas installé.")
        key = ed25519.Ed25519PrivateKey.from_private_bytes(raw_bytes)
        return cls(key)

    @classmethod
    def from_private_hex(cls, hex_str: str) -> NodeIdentity:
        return cls.from_private_bytes(bytes.fromhex(hex_str.strip()))

    def save(self, path: str | Path):
        """Enregistre la clé privée sur disque avec des permissions restreintes (0600)."""
        file_path = Path(path).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        raw_private = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        file_path.write_bytes(raw_private)
        try:
            os.chmod(file_path, 0o600)
        except Exception:
            pass

    @classmethod
    def load(cls, path: str | Path) -> NodeIdentity:
        """Charge une clé privée depuis un fichier sur disque."""
        file_path = Path(path).resolve()
        if not file_path.is_file():
            raise FileNotFoundError(f"Fichier d'identité introuvable : {file_path}")
        raw = file_path.read_bytes()
        return cls.from_private_bytes(raw)

    def sign(self, request_id: str, origin: str, skill: str, ts: float, payload: dict) -> str:
        """Signe une requête et retourne la signature au format hexadécimal."""
        data_to_sign = _signing_base(request_id, origin, skill, ts, payload, self.public_key_hex)
        sig = self._private_key.sign(data_to_sign)
        return sig.hex()


def verify_ed25519_signature(
    public_key_hex: str,
    request_id: str,
    origin: str,
    skill: str,
    ts: float,
    payload: dict,
    signature_hex: str,
) -> bool:
    """Vérifie la signature Ed25519 d'une requête."""
    if not _HAS_CRYPTO or not signature_hex or not public_key_hex:
        return False
    try:
        pubkey_bytes = bytes.fromhex(public_key_hex)
        sig_bytes = bytes.fromhex(signature_hex)
        pubkey = ed25519.Ed25519PublicKey.from_public_bytes(pubkey_bytes)
        data = _signing_base(request_id, origin, skill, ts, payload, public_key_hex)
        pubkey.verify(sig_bytes, data)
        return True
    except (InvalidSignature, ValueError, Exception):
        return False


class TrustStore:
    """Gère la liste blanche des clés publiques autorisées et les révocations."""

    def __init__(self, authorized_keys: Optional[Set[str]] = None):
        self._authorized: Set[str] = set(k.strip().lower() for k in (authorized_keys or []))
        self._name_mapping: dict[str, str] = {}  # pubkey -> name

    def add_key(self, public_key_hex: str, peer_name: Optional[str] = None):
        clean_key = public_key_hex.strip().lower()
        self._authorized.add(clean_key)
        if peer_name:
            self._name_mapping[clean_key] = peer_name

    def revoke_key(self, public_key_hex: str):
        clean_key = public_key_hex.strip().lower()
        self._authorized.discard(clean_key)
        self._name_mapping.pop(clean_key, None)

    def is_authorized(self, public_key_hex: Optional[str]) -> bool:
        if not public_key_hex:
            return False
        return public_key_hex.strip().lower() in self._authorized

    def get_peer_name(self, public_key_hex: str) -> Optional[str]:
        return self._name_mapping.get(public_key_hex.strip().lower())

    def save(self, path: str | Path):
        """Enregistre le trust store au format JSON."""
        file_path = Path(path).resolve()
        file_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "authorized_keys": sorted(list(self._authorized)),
            "names": self._name_mapping,
        }
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> TrustStore:
        """Charge un trust store depuis un fichier JSON."""
        file_path = Path(path).resolve()
        if not file_path.is_file():
            return cls()
        data = json.loads(file_path.read_text("utf-8"))
        store = cls(authorized_keys=set(data.get("authorized_keys", [])))
        store._name_mapping = data.get("names", {})
        return store
