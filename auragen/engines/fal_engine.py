"""Fal.ai backend — primary provider.

Fal hosts fast, production-grade endpoints for Flux.1, SD3.5, video models
(Kling, LTX), ControlNet variants, clarity upscaling and FILM frame
interpolation, all behind one SDK — which is why it sits first in the
fallback chain.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

from auragen.engines.base import (
    BaseEngine,
    ControlType,
    EngineNotConfigured,
    GenerationRequest,
    GenerationResult,
    RateLimitError,
    EngineError,
    Task,
)

# Logical model hint -> concrete Fal endpoint. Edit freely to track new releases.
MODEL_ROUTES: dict[str, str] = {
    "flux-dev": "fal-ai/flux/dev",
    "flux-schnell": "fal-ai/flux/schnell",
    "flux-pro": "fal-ai/flux-pro/v1.1",
    "sd35-large": "fal-ai/stable-diffusion-v35-large",
}
DEFAULT_T2I = "flux-dev"
INPAINT_ENDPOINT = "fal-ai/flux-general/inpainting"
CONTROL_ENDPOINT = "fal-ai/flux-general"
T2V_ENDPOINT = "fal-ai/ltx-video"
I2V_ENDPOINT = "fal-ai/kling-video/v1.6/standard/image-to-video"
UPSCALE_ENDPOINT = "fal-ai/clarity-upscaler"
INTERPOLATE_ENDPOINT = "fal-ai/film"

# Fal preprocessor names per control type.
_CONTROL_PATHS = {
    ControlType.CANNY: "canny",
    ControlType.DEPTH: "depth",
    ControlType.POSE: "openpose",
}


class FalEngine(BaseEngine):
    name: ClassVar[str] = "fal"
    supported_tasks: ClassVar[frozenset[Task]] = frozenset(
        {
            Task.TEXT_TO_IMAGE,
            Task.TEXT_TO_VIDEO,
            Task.IMAGE_TO_VIDEO,
            Task.INPAINT,
            Task.OUTPAINT,
            Task.CONTROL,
            Task.UPSCALE,
            Task.INTERPOLATE,
        }
    )

    def is_configured(self) -> bool:
        if not self.settings.fal_key:
            return False
        try:
            import fal_client  # noqa: F401
        except ImportError:
            return False
        return True

    # ------------------------------------------------------------------
    def _client(self):
        try:
            import fal_client
        except ImportError as exc:
            raise EngineNotConfigured("fal-client is not installed (pip install fal-client)") from exc
        if not self.settings.fal_key:
            raise EngineNotConfigured("FAL_KEY is not set")
        return fal_client

    def _subscribe(self, endpoint: str, arguments: dict[str, Any]) -> dict[str, Any]:
        fal_client = self._client()
        try:
            return fal_client.subscribe(endpoint, arguments=arguments, with_logs=False)
        except Exception as exc:  # SDK raises assorted httpx/fal errors
            message = str(exc)
            if "429" in message or "rate" in message.lower() or "quota" in message.lower():
                raise RateLimitError(f"fal rate limited on {endpoint}: {message}") from exc
            raise EngineError(f"fal call to {endpoint} failed: {message}") from exc

    def _upload(self, path: Path) -> str:
        fal_client = self._client()
        return fal_client.upload_file(str(path))

    @staticmethod
    def _collect_urls(payload: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for key in ("images", "image", "video", "videos", "output"):
            value = payload.get(key)
            if isinstance(value, dict) and value.get("url"):
                urls.append(value["url"])
            elif isinstance(value, list):
                urls.extend(item["url"] for item in value if isinstance(item, dict) and item.get("url"))
        return urls

    def _result(self, endpoint: str, payload: dict[str, Any], request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            provider=self.name,
            model_id=endpoint,
            urls=self._collect_urls(payload),
            seed=payload.get("seed", request.seed),
            raw={"endpoint": endpoint},
        )

    def _base_image_args(self, request: GenerationRequest) -> dict[str, Any]:
        args: dict[str, Any] = {
            "prompt": request.prompt,
            "image_size": {"width": request.width, "height": request.height},
            "num_images": request.num_outputs,
            "enable_safety_checker": True,
        }
        if request.negative_prompt:
            args["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            args["seed"] = request.seed
        if request.steps is not None:
            args["num_inference_steps"] = request.steps
        if request.guidance_scale is not None:
            args["guidance_scale"] = request.guidance_scale
        args.update(request.extra)
        return args

    # --- Tasks ----------------------------------------------------------
    def text_to_image(self, request: GenerationRequest) -> GenerationResult:
        endpoint = MODEL_ROUTES.get(request.model_hint or DEFAULT_T2I, MODEL_ROUTES[DEFAULT_T2I])
        payload = self._subscribe(endpoint, self._base_image_args(request))
        return self._result(endpoint, payload, request)

    def inpaint(self, request: GenerationRequest) -> GenerationResult:
        if not request.image or not request.mask:
            raise EngineError("inpaint requires --image and --mask")
        args = self._base_image_args(request)
        args["image_url"] = self._upload(request.image)
        args["mask_url"] = self._upload(request.mask)
        if request.strength is not None:
            args["strength"] = request.strength
        payload = self._subscribe(INPAINT_ENDPOINT, args)
        return self._result(INPAINT_ENDPOINT, payload, request)

    # Outpainting reuses the inpaint endpoint: image_utils pre-pads the
    # canvas and builds a border mask before we get here.
    outpaint = inpaint

    def control(self, request: GenerationRequest) -> GenerationResult:
        if not request.control_image:
            raise EngineError("control requires --ref image")
        args = self._base_image_args(request)
        ref_url = self._upload(request.control_image)
        strength = request.strength if request.strength is not None else 0.6
        if request.control_type in (ControlType.IP_ADAPTER, ControlType.REFERENCE, None):
            args["ip_adapters"] = [{"image_url": ref_url, "scale": strength}]
        else:
            args["controlnets"] = [
                {
                    "path": _CONTROL_PATHS[request.control_type],
                    "control_image_url": ref_url,
                    "conditioning_scale": strength,
                }
            ]
        payload = self._subscribe(CONTROL_ENDPOINT, args)
        return self._result(CONTROL_ENDPOINT, payload, request)

    def text_to_video(self, request: GenerationRequest) -> GenerationResult:
        args: dict[str, Any] = {"prompt": request.prompt}
        if request.negative_prompt:
            args["negative_prompt"] = request.negative_prompt
        if request.seed is not None:
            args["seed"] = request.seed
        args.update(request.extra)
        payload = self._subscribe(T2V_ENDPOINT, args)
        return self._result(T2V_ENDPOINT, payload, request)

    def image_to_video(self, request: GenerationRequest) -> GenerationResult:
        if not request.image:
            raise EngineError("image_to_video requires --image")
        args: dict[str, Any] = {
            "prompt": request.prompt,
            "image_url": self._upload(request.image),
        }
        if request.duration_seconds:
            args["duration"] = str(int(request.duration_seconds))
        if request.negative_prompt:
            args["negative_prompt"] = request.negative_prompt
        args.update(request.extra)
        payload = self._subscribe(I2V_ENDPOINT, args)
        return self._result(I2V_ENDPOINT, payload, request)

    def upscale(self, request: GenerationRequest) -> GenerationResult:
        if not request.image:
            raise EngineError("upscale requires --image")
        args = {
            "image_url": self._upload(request.image),
            "upscale_factor": request.upscale_factor or 2,
        }
        payload = self._subscribe(UPSCALE_ENDPOINT, args)
        return self._result(UPSCALE_ENDPOINT, payload, request)

    def interpolate(self, request: GenerationRequest) -> GenerationResult:
        """FILM frame interpolation over a finished video to smooth motion."""
        if not request.image:
            raise EngineError("interpolate requires --video (passed as image path)")
        args = {
            "video_url": self._upload(request.image),
            "num_frames": request.interpolation_factor or 2,
        }
        payload = self._subscribe(INTERPOLATE_ENDPOINT, args)
        return self._result(INTERPOLATE_ENDPOINT, payload, request)
