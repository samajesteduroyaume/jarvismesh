"""
Sous-package Engines : Moteurs d'inférence Apple Silicon (LLM MLX-LM, Multi-Models, Vision VLM, Audio Whisper).
"""
from ..mlx_engine import (
    MLXModelManager,
    llm,
    llm_stream,
    mlx_health_extra,
    LLMPayload,
    DEFAULT_MODEL_NAME,
)
from ..models import MultiModelManager, ModelSlot
from ..vlm_engine import VLMModelManager, get_vlm_skills, DEFAULT_VLM_MODEL
from ..audio_engine import AudioTranscriber, get_audio_skills, DEFAULT_AUDIO_MODEL

__all__ = [
    "MLXModelManager",
    "llm",
    "llm_stream",
    "mlx_health_extra",
    "LLMPayload",
    "DEFAULT_MODEL_NAME",
    "MultiModelManager",
    "ModelSlot",
    "VLMModelManager",
    "get_vlm_skills",
    "DEFAULT_VLM_MODEL",
    "AudioTranscriber",
    "get_audio_skills",
    "DEFAULT_AUDIO_MODEL",
]
