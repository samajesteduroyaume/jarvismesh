"""
Tests pour la sécurité RBAC et le contrôle des permissions (jarvismesh.rbac).
"""
import pytest
from jarvismesh.security import RBACManager


def test_rbac_default_roles_and_permissions():
    print("\n== Test RBAC: Rôles par défaut et validation de permissions ==")
    rbac = RBACManager(default_role="guest")
    
    # 1. Nœud Admin a toutes les permissions
    rbac.assign_role("node-admin-1", "admin")
    assert rbac.has_permission("node-admin-1", "skills:execute:system_exec") is True
    assert rbac.has_permission("node-admin-1", "memory:write") is True
    
    # 2. Nœud Worker
    rbac.assign_role("node-worker-1", "worker")
    assert rbac.has_permission("node-worker-1", "skills:execute:llm") is True
    assert rbac.has_permission("node-worker-1", "skills:execute:reverse") is True
    assert rbac.has_permission("node-worker-1", "skills:execute:system_exec") is False
    
    # 3. Nœud Analyst (lecture seule RAG / Graph)
    rbac.assign_role("node-analyst-1", "analyst")
    assert rbac.has_permission("node-analyst-1", "skills:execute:rag_search") is True
    assert rbac.has_permission("node-analyst-1", "skills:execute:llm") is False
    
    # 4. Nœud Guest (inconnu -> default_role)
    assert rbac.has_permission("unknown-node", "skills:execute:echo") is True
    assert rbac.has_permission("unknown-node", "skills:execute:rag_search") is False


def test_rbac_skill_authorization():
    print("\n== Test RBAC: Autorisation d'exécution de compétence ==")
    rbac = RBACManager()
    rbac.assign_role("node-guest-99", "guest")
    
    # Doit autoriser echo
    allowed, err = rbac.authorize_skill("node-guest-99", "echo")
    assert allowed is True
    assert err is None
    
    # Doit refuser llm
    allowed, err = rbac.authorize_skill("node-guest-99", "llm")
    assert allowed is False
    assert "PERMISSION_DENIED" in err


def test_rbac_custom_role():
    print("\n== Test RBAC: Définition de rôle personnalisé ==")
    rbac = RBACManager()
    rbac.define_role("auditor", ["skills:execute:memory_recall", "skills:execute:graph_query*"])
    rbac.assign_role("sec-auditor", "auditor")
    
    assert rbac.has_permission("sec-auditor", "skills:execute:memory_recall") is True
    assert rbac.has_permission("sec-auditor", "skills:execute:graph_query_relations") is True
    assert rbac.has_permission("sec-auditor", "skills:execute:llm") is False
