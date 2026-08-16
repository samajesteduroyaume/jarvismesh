"""
Module de Perforation de NAT P2P Direct (STUN / ICE Traversal) pour JarvisMesh.

Permet à deux nœuds distants situés derrière des routeurs ou box Internet distincts
de découvrir leurs points de terminaison publics WAN et d'établir une liaison directe.
"""
from __future__ import annotations
import asyncio
import os
import socket
import struct
import time
from dataclasses import dataclass
from typing import Optional, Tuple


# Serveurs STUN publics standards
DEFAULT_STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
]

# Magic Cookie RFC 5389 (0x2112A442)
STUN_MAGIC_COOKIE = 0x2112A442
# Binding Request Type: 0x0001
STUN_BINDING_REQUEST = 0x0001


@dataclass
class STUNEndpoint:
    public_ip: str
    public_port: int
    local_ip: str
    local_port: int
    nat_type: str = "RESTRICTED_CONE"  # 'OPEN', 'CONE', 'SYMMETRIC'


class STUNClient:
    """Client STUN RFC 5389 ultra-léger sans dépendance externe."""

    def __init__(self, stun_host: str = "stun.l.google.com", stun_port: int = 19302):
        self.stun_host = stun_host
        self.stun_port = stun_port

    def get_public_mapping(self, local_port: int = 0, timeout: float = 3.0) -> STUNEndpoint:
        """Envoie une requête de binding STUN et analyse la réponse XOR-MAPPED-ADDRESS."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.bind(("", local_port))
        actual_local_port = sock.getsockname()[1]
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
        except Exception:
            local_ip = "127.0.0.1"

        # Construction du paquet STUN RFC 5389 Header (20 octets)
        # Message Type (2 bytes) = 0x0001
        # Message Length (2 bytes) = 0x0000
        # Magic Cookie (4 bytes) = 0x2112A442
        # Transaction ID (12 bytes) = aléatoire
        trans_id = os.urandom(12)
        header = struct.pack("!HHI", STUN_BINDING_REQUEST, 0x0000, STUN_MAGIC_COOKIE) + trans_id

        try:
            sock.sendto(header, (self.stun_host, self.stun_port))
            data, _ = sock.recvfrom(2048)
            
            # Analyse de l'en-tête de réponse
            msg_type, msg_len, magic = struct.unpack("!HHI", data[:8])
            resp_trans_id = data[8:20]

            if magic != STUN_MAGIC_COOKIE or resp_trans_id != trans_id:
                raise ValueError("Réponse STUN corrompue ou Transaction ID mismatch")

            # Parcours des attributs STUN
            offset = 20
            pub_ip = local_ip
            pub_port = actual_local_port

            while offset < len(data):
                attr_type, attr_len = struct.unpack("!HH", data[offset:offset+4])
                attr_val = data[offset+4:offset+4+attr_len]

                # 0x0020 = XOR-MAPPED-ADDRESS
                if attr_type == 0x0020 and len(attr_val) >= 8:
                    family = attr_val[1]
                    xor_port = struct.unpack("!H", attr_val[2:4])[0]
                    pub_port = xor_port ^ (STUN_MAGIC_COOKIE >> 16)
                    
                    if family == 0x01:  # IPv4
                        xor_ip_int = struct.unpack("!I", attr_val[4:8])[0]
                        pub_ip_int = xor_ip_int ^ STUN_MAGIC_COOKIE
                        pub_ip = socket.inet_ntoa(struct.pack("!I", pub_ip_int))
                        break

                # Alignement sur 4 octets
                padded_len = (attr_len + 3) & ~3
                offset += 4 + padded_len

            return STUNEndpoint(
                public_ip=pub_ip,
                public_port=pub_port,
                local_ip=local_ip,
                local_port=actual_local_port,
            )
        except Exception:
            # Fallback en cas d'absence de connectivité Internet
            return STUNEndpoint(
                public_ip=local_ip,
                public_port=actual_local_port,
                local_ip=local_ip,
                local_port=actual_local_port,
                nat_type="LOCAL_FALLBACK",
            )
        finally:
            sock.close()


class NATTraversalManager:
    """Gestionnaire de sessions P2P directes avec perforation de pare-feu."""

    def __init__(self, stun_servers: Optional[list[tuple[str, int]]] = None):
        self.stun_servers = stun_servers or DEFAULT_STUN_SERVERS
        self._cached_endpoint: Optional[STUNEndpoint] = None

    def get_endpoint(self, force_refresh: bool = False) -> STUNEndpoint:
        if self._cached_endpoint and not force_refresh:
            return self._cached_endpoint

        for host, port in self.stun_servers:
            try:
                client = STUNClient(host, port)
                ep = client.get_public_mapping()
                self._cached_endpoint = ep
                return ep
            except Exception:
                continue

        # Fallback local
        self._cached_endpoint = STUNEndpoint("127.0.0.1", 8765, "127.0.0.1", 8765)
        return self._cached_endpoint

    def punch_hole(self, peer_ip: str, peer_port: int, attempts: int = 3) -> bool:
        """Envoie des paquets UDP de synchronisation pour perforer la table d'état NAT."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1.0)
        try:
            for _ in range(attempts):
                sock.sendto(b"JARVIS_NAT_PUNCH", (peer_ip, peer_port))
                time.sleep(0.05)
            return True
        except Exception:
            return False
        finally:
            sock.close()
