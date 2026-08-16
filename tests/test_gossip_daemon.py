"""
Tests unitaires pour le protocole Gossip SWIM et le gestionnaire de démon système.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvismesh.gossip import GossipCluster, GossipMember, MemberState
from jarvismesh.daemon import (
    ServiceManager,
    generate_macos_plist,
    generate_systemd_unit,
)


def test_gossip_membership_and_merge():
    print("== Test 1: Protocole Gossip SWIM — Gestion des membres & fusions ==")
    cluster = GossipCluster(
        local_name="node-paris",
        local_host="192.168.1.10",
        local_port=8001,
        local_skills=["echo", "mlx"],
    )

    assert len(cluster.members) == 1
    assert cluster.members["node-paris"].state == MemberState.ALIVE

    # Fusion avec une mise à jour reçue d'un pair
    remote_digest = [
        {
            "name": "node-tokyo",
            "host": "192.168.1.20",
            "port": 8002,
            "skills": ["rag_search", "weather"],
            "incarnation": 1,
            "state": "alive",
        },
        {
            "name": "node-nyc",
            "host": "192.168.1.30",
            "port": 8003,
            "skills": ["mcp_tools"],
            "incarnation": 2,
            "state": "suspect",
        },
    ]

    updated = cluster.merge_members(remote_digest)
    assert "node-tokyo" in updated
    assert "node-nyc" in updated
    assert len(cluster.members) == 3

    # Cartographie des compétences du cluster
    skills_map = cluster.get_skills_map()
    assert "echo" in skills_map
    assert "rag_search" in skills_map
    print(f"  -> Cartographie des compétences actives du cluster: {skills_map}")


def test_daemon_service_generation():
    print("\n== Test 2: Génération des configurations launchd et systemd ==")

    plist = generate_macos_plist("mac-selim", 8888, python_bin="/usr/bin/python3")
    assert plist["Label"] == "com.jarvismesh.agent"
    assert plist["RunAtLoad"] is True
    assert "--name" in plist["ProgramArguments"]
    assert "mac-selim" in plist["ProgramArguments"]
    print(f"  -> Plist macOS validé : Label={plist['Label']}, Args={' '.join(plist['ProgramArguments'][:4])}...")

    unit = generate_systemd_unit("linux-selim", 8888, python_bin="/usr/bin/python3")
    assert "[Unit]" in unit
    assert "ExecStart=" in unit
    assert "linux-selim" in unit
    print("  -> Unité systemd Linux validée")

    # Vérification de ServiceManager
    mgr = ServiceManager()
    status = mgr.status()
    assert "os" in status
    assert "installed" in status
    print(f"  -> Détection OS hôte: {status['os']} (Installé: {status['installed']})")


if __name__ == "__main__":
    test_gossip_membership_and_merge()
    test_daemon_service_generation()
    print("\nTous les tests Gossip & Démon sont passés avec succès !")
