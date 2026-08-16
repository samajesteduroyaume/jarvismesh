"""
Moteur d'inférence LLM locale et télémétrie Metal GPU (Apple Silicon) via MLX-LM.
"""
from __future__ import annotations
import os
from typing import Any, Generator, Optional

try:
    from pydantic import BaseModel, Field, model_validator
    _HAS_PYDANTIC = True
except ImportError:
    BaseModel = object  # type: ignore
    Field = lambda *args, **kwargs: None  # type: ignore
    model_validator = lambda *args, **kwargs: (lambda f: f)  # type: ignore
    _HAS_PYDANTIC = False

try:
    import mlx.core as mx
    from mlx_lm import load as mlx_load, generate as mlx_generate, stream_generate as mlx_stream_generate
    from mlx_lm.sample_utils import make_sampler
    _HAS_MLX = True
except ImportError:
    _HAS_MLX = False


DEFAULT_MODEL_NAME = os.environ.get("JARVISMESH_MODEL", "mlx-community/Qwen3.5-4B-MLX-4bit")


class MLXModelManager:
    """Gestionnaire de modèles MLX en singleton / cache pour éviter de
    recharger les poids à chaque requête."""
    _model = None
    _tokenizer = None
    _loaded_model_name: Optional[str] = None

    @classmethod
    def get_model(cls, model_name: Optional[str] = None):
        if not _HAS_MLX:
            raise ImportError(
                "mlx-lm n'est pas installé. Installez-le avec `pip install mlx-lm` "
                "ou `pip install -e '.[mlx]'` sur une machine Apple Silicon."
            )
        target = model_name or DEFAULT_MODEL_NAME
        if cls._model is None or cls._loaded_model_name != target:
            cls._model, cls._tokenizer = mlx_load(target)
            cls._loaded_model_name = target
        return cls._model, cls._tokenizer, cls._loaded_model_name

    @classmethod
    def loaded_model_name(cls) -> Optional[str]:
        return cls._loaded_model_name

    @classmethod
    def format_prompt(cls, tokenizer, prompt: Optional[str] = None,
                      system_prompt: Optional[str] = None,
                      messages: Optional[list[dict[str, str]]] = None) -> str:
        """Formate le prompt en utilisant le template Jinja du tokenizer si disponible."""
        if messages:
            chat_messages = list(messages)
            if system_prompt and not any(m.get("role") == "system" for m in chat_messages):
                chat_messages.insert(0, {"role": "system", "content": system_prompt})
            if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
                try:
                    return tokenizer.apply_chat_template(
                        chat_messages, tokenize=False, add_generation_prompt=True
                    )
                except Exception:
                    pass
            # Fallback simple
            return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in chat_messages)

        text = prompt or ""
        if hasattr(tokenizer, "apply_chat_template") and tokenizer.chat_template:
            chat_messages = []
            if system_prompt:
                chat_messages.append({"role": "system", "content": system_prompt})
            chat_messages.append({"role": "user", "content": text})
            try:
                return tokenizer.apply_chat_template(
                    chat_messages, tokenize=False, add_generation_prompt=True
                )
            except Exception:
                pass
        if system_prompt:
            return f"System: {system_prompt}\nUser: {text}\nAssistant:"
        return text


if _HAS_PYDANTIC:
    class LLMPayload(BaseModel):
        prompt: Optional[str] = Field(default=None, min_length=1, max_length=50_000)
        messages: Optional[list[dict[str, Any]]] = Field(default=None)
        system_prompt: Optional[str] = Field(default=None, max_length=10_000)
        max_tokens: int = Field(default=512, ge=1, le=8192)
        temperature: float = Field(default=0.7, ge=0.0, le=2.0)
        model: Optional[str] = Field(default=None)

        @model_validator(mode="after")
        def check_prompt_or_messages(self):
            if not self.prompt and not self.messages:
                raise ValueError("Au moins 'prompt' ou 'messages' doit être fourni et non vide.")
            return self
else:
    class LLMPayload:  # type: ignore
        pass


def llm(payload: dict) -> dict:
    """Exécution LLM complète via MLX (ou fallback simulé si MLX non installé)."""
    prompt = payload.get("prompt")
    messages = payload.get("messages")
    system_prompt = payload.get("system_prompt")
    max_tokens = payload.get("max_tokens", 512)
    temperature = payload.get("temperature", 0.7)
    model_name = payload.get("model")

    if not _HAS_MLX:
        raise RuntimeError("Le moteur MLX-LM n'est pas disponible sur cette machine. Installez mlx-lm via `pip install '.[mlx]'`.")

    model, tokenizer, active_model_name = MLXModelManager.get_model(model_name)
    formatted = MLXModelManager.format_prompt(
        tokenizer, prompt=prompt, system_prompt=system_prompt, messages=messages
    )
    sampler = make_sampler(temp=temperature)

    response_text = mlx_generate(
        model,
        tokenizer,
        prompt=formatted,
        max_tokens=max_tokens,
        sampler=sampler,
    )
    return {
        "response": response_text.strip(),
        "model": active_model_name,
    }


def llm_stream(payload: dict) -> Generator[str, None, None]:
    """Génération LLM en flux continu token-par-token via MLX."""
    prompt = payload.get("prompt")
    messages = payload.get("messages")
    system_prompt = payload.get("system_prompt")
    max_tokens = payload.get("max_tokens", 512)
    temperature = payload.get("temperature", 0.7)
    model_name = payload.get("model")

    if not _HAS_MLX:
        raise RuntimeError("Le moteur MLX-LM n'est pas disponible sur cette machine. Installez mlx-lm via `pip install '.[mlx]'`.")

    model, tokenizer, _ = MLXModelManager.get_model(model_name)
    formatted = MLXModelManager.format_prompt(
        tokenizer, prompt=prompt, system_prompt=system_prompt, messages=messages
    )
    sampler = make_sampler(temp=temperature)

    for chunk in mlx_stream_generate(
        model,
        tokenizer,
        prompt=formatted,
        max_tokens=max_tokens,
        sampler=sampler,
    ):
        if chunk.text:
            yield chunk.text


def mlx_health_extra() -> dict:
    """Retourne les métriques de mémoire Metal et le modèle chargé pour
    enrichir la compétence interne '_health'."""
    metrics: dict[str, Any] = {
        "mlx_available": _HAS_MLX,
        "loaded_model": MLXModelManager.loaded_model_name(),
    }
    if _HAS_MLX:
        try:
            if hasattr(mx, "get_active_memory"):
                active_b = mx.get_active_memory()
                peak_b = mx.get_peak_memory()
                cache_b = mx.get_cache_memory()
            else:
                active_b = mx.metal.get_active_memory()
                peak_b = mx.metal.get_peak_memory()
                cache_b = mx.metal.get_cache_memory()

            metrics["metal_active_mb"] = round(active_b / (1024 * 1024), 2)
            metrics["metal_peak_mb"] = round(peak_b / (1024 * 1024), 2)
            metrics["metal_cache_mb"] = round(cache_b / (1024 * 1024), 2)
        except Exception:
            pass
    return metrics
