"""
Tests pour la perforation de NAT P2P et le client STUN (jarvismesh.nat_p2p).
"""
import pytest
from jarvismesh.core import STUNClient, NATTraversalManager, STUNEndpoint


def test_nat_traversal_manager():
    print("\n== Test NAT: Découverte de point de terminaison et perforation ==")
    manager = NATTraversalManager()
    
    # Résolution d'endpoint (avec fallback local si hors-ligne)
    ep = manager.get_endpoint()
    assert isinstance(ep, STUNEndpoint)
    assert ep.local_port > 0
    assert len(ep.public_ip) > 0
    
    # Test de simulation de perforation UDP
    punched = manager.punch_hole("127.0.0.1", 9999, attempts=2)
    assert punched is True


def test_stun_client_mock_binding():
    print("\n== Test STUN: Client STUN binding RFC 5389 ==")
    client = STUNClient("127.0.0.1", 19302)
    # Vérification du fallback propre si le serveur STUN local ne répond pas
    ep = client.get_public_mapping(local_port=0, timeout=0.2)
    assert ep.nat_type in ("LOCAL_FALLBACK", "RESTRICTED_CONE")
    assert ep.local_port > 0
