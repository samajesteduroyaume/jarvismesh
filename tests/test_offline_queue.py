"""
Tests pour la file d'attente persistante et résilience hors-ligne (Store & Forward).
"""
import pytest
from jarvismesh.offline_queue import PersistentTaskQueue


async def test_offline_task_queue_store_and_forward():
    print("\n== Test PersistentTaskQueue: Mise en spool et flush automatique ==")
    queue = PersistentTaskQueue(":memory:")
    
    # 1. Enfile 2 tâches pour un nœud temporairement hors-ligne (worker-node-1)
    tid1 = queue.enqueue("worker-node-1", "llm", {"prompt": "Bonjour"}, max_attempts=3)
    tid2 = queue.enqueue("worker-node-1", "reverse", {"text": "mesh"}, max_attempts=3)
    
    stats = queue.stats()
    assert stats["PENDING"] == 2
    
    # 2. Le nœud réapparaît : on lance le dispatcher
    dispatched_skills = []
    
    async def mock_dispatcher(skill: str, payload: dict) -> dict:
        dispatched_skills.append((skill, payload))
        return {"done": True}
    
    results = await queue.flush_node("worker-node-1", mock_dispatcher)
    assert len(results) == 2
    assert results[0]["ok"] is True
    assert results[1]["ok"] is True
    assert len(dispatched_skills) == 2
    
    # 3. Vérification des stats après succès
    stats_after = queue.stats()
    assert stats_after["PENDING"] == 0
    assert stats_after["SUCCESS"] == 2
    
    queue.close()


async def test_offline_task_queue_retry_and_failure():
    print("\n== Test PersistentTaskQueue: Échecs et retry avec backoff ==")
    queue = PersistentTaskQueue(":memory:")
    
    tid = queue.enqueue("worker-fail", "bad_skill", {}, max_attempts=2)
    
    async def failing_dispatcher(skill: str, payload: dict):
        raise ConnectionRefusedError("Pair injoignable")
    
    # Première tentative -> échec mais reste PENDING avec retry futur
    res1 = await queue.flush_node("worker-fail", failing_dispatcher)
    assert res1[0]["ok"] is False
    
    # Deuxième tentative forcée
    queue.mark_failure(tid, "Erreur répétée", backoff_base_sec=1.0)
    
    stats = queue.stats()
    assert stats["FAILED"] == 1
    
    queue.close()
