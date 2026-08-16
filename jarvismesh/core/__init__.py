"""
Sous-package Core : Réseau P2P, Protocoles, Multiplexage, NAT, WAN et Gossip.
"""
from ..node import JarvisNode
from ..protocol import (
    PROTOCOL_VERSION,
    SERVICE_TYPE,
    DESCRIBE_SKILL,
    HEALTH_SKILL,
    RESERVED_SKILLS,
    TaskRequest,
    TaskResponse,
    TaskChunk,
    sign_request,
    verify_request,
    parse_message,
)
from ..binary_protocol import BinaryMessageEncoder, MAGIC_BINARY_HEADER
from ..nat_p2p import STUNClient, NATTraversalManager, STUNEndpoint
from ..wan import MeshRelayServer, WANPeerManager, detect_tailscale_ip
from ..gossip import GossipCluster, GossipMember, MemberState

__all__ = [
    "JarvisNode",
    "PROTOCOL_VERSION",
    "SERVICE_TYPE",
    "DESCRIBE_SKILL",
    "HEALTH_SKILL",
    "RESERVED_SKILLS",
    "TaskRequest",
    "TaskResponse",
    "TaskChunk",
    "sign_request",
    "verify_request",
    "parse_message",
    "BinaryMessageEncoder",
    "MAGIC_BINARY_HEADER",
    "STUNClient",
    "NATTraversalManager",
    "STUNEndpoint",
    "MeshRelayServer",
    "WANPeerManager",
    "detect_tailscale_ip",
    "GossipCluster",
    "GossipMember",
    "MemberState",
]
