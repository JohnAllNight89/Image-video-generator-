"""Replicate backend — first fallback.

Covers text-to-image (Flux, SD3.5), inpainting, ControlNet and upscaling.
Model versions are pinned loosely by owner/name so Replicate resolves the
latest published version.
"""

from __future__ import annotations

from typing import Any, ClassVar

from auragen.engines.base import (
    BaseEngine,
    ControlType,
    EngineError,
    EngineNotConfigured,
    GenerationRequest,
    GenerationResult,
    RateLimitError,
    Task,
)

MODEL_ROUTES: dict[str, str] = {
    "flux-dev": "black-forest-labs/flux-dev",
    "flux-schnell": "black-forest-labs/flux-schnell",
    "flux-pro": "black-forest-labs/flux-1.1-pro",
    "sd35-large": "stability-ai/stable-diffusion-3.5-large",
}
DEFAULT_T2I = "flux-dev"
INPAINT_MODEL = "black-forest-labs/flux-fill-dev"
CONTROL_MODELS = {
    ControlType.CANNY: "black-forest-labs/flux-canny-dev",
    ControlType.DEPTH: "black-forest-labs/flux-depth-dev",
}
REDUX_MODEL = "black-forest-labs/flux-redux-dev"  # reference / IP-adapter-style
UPSCALE_MODEL = "nightmareai/real-esrgan"
T2V_MODEL = "lightricks/ltx-video"


def _aspect_ratio(width: int, height: int) -> str:
    from math import gcd

    divisor = gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


class ReplicateEngine(BaseEngine):
    name: ClassVar[str] = "replicate"
    supported_tasks: ClassVar[frozenset[Task]] = frozenset(
        {
            Task.TEXT_TO_IMAGE,
            Task.TEXT_TO_VIDEO,
            Task.INPAINT,
            Task.OUTPAINT,
            Task.CONTROL,
            Task.UPSCALE,
        }
    )

    def is_configured(self) -> bool:
        if not self.settings.replicate_api_token:
            return False
        try:
            import replicate  # noqa: F401
        except ImportError:
            return False
        return True

    def _run(self, model: str, payload: dict[str, Any]) -> list[str]:
        try:
            import replicate
            from replicate.exceptions import ReplicateError
        except ImportError as exc:
            raise EngineNotConfigured("replicate is not installed (pip install replicate)") from exc
        if not self.settings.replicate_api_token:
            raise EngineNotConfigured("REPLICATE_API_TOKEN is not set")
        try:
            output = replicate.run(model, input=payload, use_file_output=False)
        except ReplicateError as exc:
            status = getattr(exc, "status", None)
            if status == 429 or "rate" in str(exc).lower():
                raise RateLimitError(f"replicate rate limited on {model}: {exc}") from exc
            raise EngineError(f"replicate call to {model} failed: {exc}") from exc
        except Exception as exc:
            raise EngineError(f"replicate call to {model} failed: {exc}") from exc

        if isinstance(output, str):
            return [output]
        if isinstance(output, (list, tuple)):
            return [str(item) for item in output]
        return [str(output)]

    def _result(self, model: str, urls: list[str], request: GenerationRequest) -> GenerationResult:
        return GenerationResult(provider=self.name, model_id=model, urls=urls, seed=request.seed)

    def _common_args(self, request: GenerationRequest) -> dict[str, Any]:
        args: dict[str, Any] = {
            "prompt": request.prompt,
            "num_outputs": request.num_outputs,
            "output_format": "png",
        }
        if request.seed is not None:
            args["seed"] = request.seed
        if request.guidance_scale is not None:
            args["guidance"] = request.guidance_scale
        if request.steps is not None:
            args["num_inference_steps"] = request.steps
        if request.negative_prompt:
            # Flux ignores it; SD3.5 honors it. Harmless either way.
            args["negative_prompt"] = request.negative_prompt
        args.update(request.extra)
        return args

    # --- Tasks ----------------------------------------------------------
    def text_to_image(self, request: GenerationRequest) -> GenerationResult:
        model = MODEL_ROUTES.get(request.model_hint or DEFAULT_T2I, MODEL_ROUTES[DEFAULT_T2I])
        args = self._common_args(request)
        args["aspect_ratio"] = _aspect_ratio(request.width, request.height)
        return self._result(model, self._run(model, args), request)

    def inpaint(self, request: GenerationRequest) -> GenerationResult:
        if not request.image or not request.mask:
            raise EngineError("inpaint requires --image and --mask")
        args = self._common_args(request)
        args["image"] = open(request.image, "rb")
        args["mask"] = open(request.mask, "rb")
        return self._result(INPAINT_MODEL, self._run(INPAINT_MODEL, args), request)

    outpaint = inpaint

    def control(self, request: GenerationRequest) -> GenerationResult:
        if not request.control_image:
            raise EngineError("control requires --ref image")
        if request.control_type in (ControlType.IP_ADAPTER, ControlType.REFERENCE, None):
            model = REDUX_MODEL
            args = self._common_args(request)
            args["redux_image"] = open(request.control_image, "rb")
        elif request.control_type in CONTROL_MODELS:
            model = CONTROL_MODELS[request.control_type]
            args = self._common_args(request)
            args["control_image"] = open(request.control_image, "rb")
        else:
            raise EngineError(f"replicate backend has no route for control type {request.control_type}")
        return self._result(model, self._run(model, args), request)

    def text_to_video(self, request: GenerationRequest) -> GenerationResult:
        args: dict[str, Any] = {"prompt": request.prompt}
        if request.negative_prompt:
            args["negative_prompt"] = request.negative_prompt
        args.update(request.extra)
        return self._result(T2V_MODEL, self._run(T2V_MODEL, args), request)

    def upscale(self, request: GenerationRequest) -> GenerationResult:
        if not request.image:
            raise EngineError("upscale requires --image")
        args = {"image": open(request.image, "rb"), "scale": request.upscale_factor or 2}
        return self._result(UPSCALE_MODEL, self._run(UPSCALE_MODEL, args), request)
