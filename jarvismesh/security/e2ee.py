"""
Module de Chiffrement de Bout en Bout (E2EE - End-to-End Encryption) pour JarvisMesh.

Garantit la confidentialité et l'intégrité absolue des flux et données échangés
entre agents via un échange de clés asymétrique Diffie-Hellman X25519
et un chiffrement symétrique authentifié ChaCha20-Poly1305.
"""
from __future__ import annotations
import base64
import json
import os
from typing import Any, Optional, Tuple

try:
    from cryptography.hazmat.primitives.asymmetric import x25519
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes, serialization
    _HAS_E2EE = True
except ImportError:
    _HAS_E2EE = False


def _require_e2ee():
    if not _HAS_E2EE:
        raise ImportError(
            "La bibliothèque 'cryptography' est requise pour le chiffrement E2EE. "
            "Installez-la via `pip install cryptography` ou `pip install -e .`"
        )


class E2EEIdentity:
    """Identité Diffie-Hellman X25519 d'un nœud pour le chiffrement de bout en bout."""

    def __init__(self, private_key: Optional["x25519.X25519PrivateKey"] = None):
        _require_e2ee()
        self._private_key = private_key or x25519.X25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()
        self.public_key_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        self.public_key_hex = self.public_key_bytes.hex()

    @classmethod
    def generate(cls) -> E2EEIdentity:
        """Génère une nouvelle paire de clés X25519."""
        return cls()

    @classmethod
    def from_private_bytes(cls, raw_bytes: bytes) -> E2EEIdentity:
        """Charge une clé privée X25519 depuis 32 octets bruts."""
        _require_e2ee()
        key = x25519.X25519PrivateKey.from_private_bytes(raw_bytes)
        return cls(key)

    @classmethod
    def from_private_hex(cls, hex_str: str) -> E2EEIdentity:
        """Charge une clé privée X25519 depuis une chaîne hexadécimale."""
        return cls.from_private_bytes(bytes.fromhex(hex_str))

    @property
    def private_key_hex(self) -> str:
        """Exporte la clé privée en hexadécimal."""
        raw = self._private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        return raw.hex()

    def derive_shared_key(self, peer_public_key_hex: str, salt: Optional[bytes] = None) -> bytes:
        """Dérive une clé symétrique partagée de 32 octets via ECDH X25519 + HKDF-SHA256."""
        _require_e2ee()
        peer_pub_bytes = bytes.fromhex(peer_public_key_hex)
        peer_public_key = x25519.X25519PublicKey.from_public_bytes(peer_pub_bytes)
        
        shared_secret = self._private_key.exchange(peer_public_key)
        
        hkdf = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt or b"jarvismesh-e2ee-v1",
            info=b"mesh-session-key",
        )
        return hkdf.derive(shared_secret)


class E2EESession:
    """Session de chiffrement authentifié ChaCha20-Poly1305 entre deux nœuds."""

    def __init__(self, shared_key: bytes):
        _require_e2ee()
        if len(shared_key) != 32:
            raise ValueError("La clé symétrique ChaCha20-Poly1305 doit faire exactement 32 octets.")
        self.shared_key = shared_key
        self._cipher = ChaCha20Poly1305(shared_key)

    @classmethod
    def from_identities(cls, local_identity: E2EEIdentity, peer_public_key_hex: str) -> E2EESession:
        """Crée une session E2EE directement depuis l'identité locale et la clé publique du pair."""
        shared_key = local_identity.derive_shared_key(peer_public_key_hex)
        return cls(shared_key)

    def encrypt(self, data: Any, associated_data: Optional[bytes] = None) -> dict[str, str]:
        """Chiffre des données (dict, str, list) et retourne une enveloppe E2EE sécurisée."""
        if not isinstance(data, (bytes, bytearray)):
            plaintext = json.dumps(data, sort_keys=True).encode("utf-8")
        else:
            plaintext = bytes(data)

        # Nonce aléatoire standard ChaCha20-Poly1305 (12 octets / 96 bits)
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(nonce, plaintext, associated_data)

        return {
            "e2ee": True,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }

    def decrypt(self, envelope: dict[str, Any], associated_data: Optional[bytes] = None) -> Any:
        """Déchiffre une enveloppe E2EE et retourne le contenu d'origine."""
        if not envelope.get("e2ee"):
            raise ValueError("L'enveloppe fournie n'est pas marquée comme chiffrée E2EE.")

        nonce = base64.b64decode(envelope["nonce"])
        ciphertext = base64.b64decode(envelope["ciphertext"])

        plaintext_bytes = self._cipher.decrypt(nonce, ciphertext, associated_data)
        try:
            return json.loads(plaintext_bytes.decode("utf-8"))
        except Exception:
            return plaintext_bytes.decode("utf-8")


def encrypt_for_peer(peer_pubkey_hex: str, payload: dict, local_identity: Optional[E2EEIdentity] = None) -> dict[str, Any]:
    """Chiffre un payload de manière asymétrique (clé éphémère ou identité locale) à destination d'un pair."""
    identity = local_identity or E2EEIdentity.generate()
    session = E2EESession.from_identities(identity, peer_pubkey_hex)
    envelope = session.encrypt(payload)
    envelope["sender_pubkey"] = identity.public_key_hex
    return envelope


def decrypt_from_peer(envelope: dict[str, Any], local_identity: E2EEIdentity) -> Any:
    """Déchiffre une enveloppe reçue en utilisant l'identité locale et la clé publique de l'expéditeur."""
    sender_pubkey_hex = envelope.get("sender_pubkey")
    if not sender_pubkey_hex:
        raise ValueError("Enveloppe E2EE invalide : champ 'sender_pubkey' manquant.")
    session = E2EESession.from_identities(local_identity, sender_pubkey_hex)
    return session.decrypt(envelope)
