"""Hugging Face Inference API backend — second fallback.

Text-to-image only, but it keeps the pipeline alive when both paid
providers are rate limited. Returns PIL images which we persist directly
(no URL round-trip).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import ClassVar

from auragen.engines.base import (
    BaseEngine,
    EngineError,
    EngineNotConfigured,
    GenerationRequest,
    GenerationResult,
    RateLimitError,
    Task,
)

MODEL_ROUTES: dict[str, str] = {
    "flux-dev": "black-forest-labs/FLUX.1-dev",
    "flux-schnell": "black-forest-labs/FLUX.1-schnell",
    "sd35-large": "stabilityai/stable-diffusion-3.5-large",
}
DEFAULT_T2I = "flux-dev"


class HuggingFaceEngine(BaseEngine):
    name: ClassVar[str] = "huggingface"
    supported_tasks: ClassVar[frozenset[Task]] = frozenset({Task.TEXT_TO_IMAGE})

    def is_configured(self) -> bool:
        if not self.settings.hf_token:
            return False
        try:
            import huggingface_hub  # noqa: F401
        except ImportError:
            return False
        return True

    def text_to_image(self, request: GenerationRequest) -> GenerationResult:
        try:
            from huggingface_hub import InferenceClient
            from huggingface_hub.errors import HfHubHTTPError
        except ImportError as exc:
            raise EngineNotConfigured("huggingface_hub is not installed") from exc
        if not self.settings.hf_token:
            raise EngineNotConfigured("HF_TOKEN is not set")

        model = MODEL_ROUTES.get(request.model_hint or DEFAULT_T2I, MODEL_ROUTES[DEFAULT_T2I])
        client = InferenceClient(token=self.settings.hf_token, timeout=self.settings.request_timeout_seconds)

        files: list[Path] = []
        try:
            for _ in range(request.num_outputs):
                image = client.text_to_image(
                    request.prompt,
                    model=model,
                    negative_prompt=request.negative_prompt or None,
                    width=request.width,
                    height=request.height,
                    num_inference_steps=request.steps,
                    guidance_scale=request.guidance_scale,
                    seed=request.seed,
                )
                handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="auragen_hf_")
                image.save(handle.name)
                files.append(Path(handle.name))
        except HfHubHTTPError as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status == 429:
                raise RateLimitError(f"huggingface rate limited on {model}: {exc}") from exc
            raise EngineError(f"huggingface call to {model} failed: {exc}") from exc
        except Exception as exc:
            raise EngineError(f"huggingface call to {model} failed: {exc}") from exc

        return GenerationResult(provider=self.name, model_id=model, files=files, seed=request.seed)
