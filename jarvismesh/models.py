"""
Module de gestion multi-modèles et cache LRU de mémoire Metal GPU pour JarvisMesh.

Permet à un nœud d'héberger et de basculer dynamiquement entre plusieurs modèles
de tailles et spécialités différentes (ex: 1B routing + 7B deep reasoning)
avec déchargement automatique (LRU) de la VRAM Metal pour éviter la saturation.
"""
from __future__ import annotations
import gc
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional, Tuple

from .mlx_engine import (
    DEFAULT_MODEL_NAME,
    MLXModelManager,
    _HAS_MLX,
    mlx_health_extra,
)


@dataclass
class ModelSlot:
    """Emplacement d'un modèle chargé en mémoire."""
    model_name: str
    model: Any
    tokenizer: Any
    last_used: float = field(default_factory=time.time)
    use_count: int = 0


class MultiModelManager:
    """Gestionnaire de cycle de vie multi-modèles avec politique d'éviction LRU."""

    def __init__(self, max_loaded: int = 2, default_model: str = DEFAULT_MODEL_NAME):
        self.max_loaded = max_loaded
        self.default_model = default_model
        self._slots: dict[str, ModelSlot] = {}

    @property
    def loaded_models(self) -> list[str]:
        return list(self._slots.keys())

    def get_slot(self, model_name: Optional[str] = None) -> ModelSlot:
        """Récupère ou charge un modèle selon la politique LRU."""
        target_name = model_name or self.default_model

        if target_name in self._slots:
            slot = self._slots[target_name]
            slot.last_used = time.time()
            slot.use_count += 1
            return slot

        # Vérification de la limite de capacité : éviction LRU
        if len(self._slots) >= self.max_loaded:
            self._evict_lru()

        # Chargement du nouveau modèle
        if not _HAS_MLX:
            raise RuntimeError(
                "Le paquet 'mlx-lm' n'est pas installé. "
                "Installez-le avec `pip install mlx-lm` pour activer l'inférence locale."
            )

        from mlx_lm import load
        model, tokenizer = load(target_name)
        slot = ModelSlot(
            model_name=target_name,
            model=model,
            tokenizer=tokenizer,
            last_used=time.time(),
            use_count=1,
        )
        self._slots[target_name] = slot
        return slot

    def _evict_lru(self) -> Optional[str]:
        """Décharge le modèle le moins récemment utilisé."""
        if not self._slots:
            return None

        oldest_name = min(self._slots.keys(), key=lambda k: self._slots[k].last_used)
        del self._slots[oldest_name]

        # Forcer le garbage collector pour libérer la VRAM Metal
        gc.collect()
        if _HAS_MLX:
            try:
                import mlx.core as mx
                if hasattr(mx, "metal") and hasattr(mx.metal, "clear_cache"):
                    mx.metal.clear_cache()
            except Exception:
                pass
        return oldest_name

    def unload(self, model_name: str) -> bool:
        """Décharge explicitement un modèle de la mémoire."""
        if model_name in self._slots:
            del self._slots[model_name]
            gc.collect()
            return True
        return False

    def generate(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> dict[str, Any]:
        """Génération synchrone via le modèle sélectionné."""
        slot = self.get_slot(model_name)
        start_t = time.time()

        from mlx_lm import generate
        response = generate(
            slot.model,
            slot.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            temp=temperature,
            verbose=False,
        )
        duration = time.time() - start_t
        metrics = mlx_health_extra()

        return {
            "response": response,
            "model": slot.model_name,
            "duration_sec": round(duration, 3),
            "memory": metrics,
        }

    async def generate_stream(
        self,
        prompt: str,
        model_name: Optional[str] = None,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Génération en continu token-par-token via le modèle sélectionné."""
        slot = self.get_slot(model_name)
        from mlx_lm.utils import stream_generate
        for item in stream_generate(slot.model, slot.tokenizer, prompt=prompt, max_tokens=max_tokens, temp=temperature):
            # item est un GenerationResponse(text=..., ...)
            yield getattr(item, "text", str(item))

    def get_status(self) -> dict[str, Any]:
        """Retourne l'état des modèles chargés et métriques Metal."""
        return {
            "max_loaded": self.max_loaded,
            "loaded_models": [
                {
                    "name": s.model_name,
                    "last_used": s.last_used,
                    "use_count": s.use_count,
                }
                for s in self._slots.values()
            ],
            "metal_metrics": mlx_health_extra(),
        }
