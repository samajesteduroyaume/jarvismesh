"""
Tests pour le gestionnaire multi-modèles et cache LRU Metal GPU (jarvismesh.models).
"""
import pytest
from unittest.mock import MagicMock, patch
from jarvismesh.models import MultiModelManager, ModelSlot


def test_multi_model_lru_eviction():
    print("\n== Test MultiModelManager: Éviction LRU de VRAM ==")
    
    # Mock du chargement mlx_lm
    with patch("jarvismesh.models._HAS_MLX", True), \
         patch("mlx_lm.load") as mock_load:
        
        mock_load.side_effect = lambda name: (MagicMock(name=f"model_{name}"), MagicMock(name=f"tok_{name}"))
        
        mgr = MultiModelManager(max_loaded=2, default_model="model-1")
        
        # 1. Charge model-1
        slot1 = mgr.get_slot("model-1")
        assert slot1.model_name == "model-1"
        assert len(mgr.loaded_models) == 1
        
        # 2. Charge model-2
        slot2 = mgr.get_slot("model-2")
        assert slot2.model_name == "model-2"
        assert len(mgr.loaded_models) == 2
        
        # 3. Réutilise model-1 (devient le plus récent)
        _ = mgr.get_slot("model-1")
        
        # 4. Charge model-3 -> doit évincer model-2 car model-1 a été utilisé plus récemment
        slot3 = mgr.get_slot("model-3")
        assert slot3.model_name == "model-3"
        assert len(mgr.loaded_models) == 2
        assert "model-2" not in mgr.loaded_models
        assert "model-1" in mgr.loaded_models
        assert "model-3" in mgr.loaded_models


def test_multi_model_status():
    with patch("jarvismesh.models._HAS_MLX", True), \
         patch("mlx_lm.load") as mock_load:
        mock_load.side_effect = lambda name: (MagicMock(), MagicMock())
        mgr = MultiModelManager(max_loaded=3)
        mgr.get_slot("mlx-community/Qwen2.5-0.5B-Instruct-4bit")
        
        status = mgr.get_status()
        assert status["max_loaded"] == 3
        assert len(status["loaded_models"]) == 1
        assert status["loaded_models"][0]["name"] == "mlx-community/Qwen2.5-0.5B-Instruct-4bit"
