"""Abstract engine contract.

A *backend engine* (Fal, Replicate, Hugging Face, ComfyUI) knows how to
execute low-level tasks. High-level pipelines (GenEngine, EditEngine,
DesignEngine, ControlEngine in ``auragen.engines.pipelines``) compose these
via the APIManager, which handles fallback between backends.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from auragen.config.settings import AuraGenSettings


class Task(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    TEXT_TO_VIDEO = "text_to_video"
    IMAGE_TO_VIDEO = "image_to_video"
    INPAINT = "inpaint"
    OUTPAINT = "outpaint"
    CONTROL = "control"
    UPSCALE = "upscale"
    INTERPOLATE = "interpolate"


class EngineError(RuntimeError):
    """Base class for engine failures."""


class EngineNotConfigured(EngineError):
    """The engine is missing credentials or its SDK is not installed."""


class RateLimitError(EngineError):
    """Provider signalled a rate limit / quota exhaustion (retryable, then fall back)."""


class TaskNotSupported(EngineError):
    """This backend cannot perform the requested task."""


class ControlType(str, Enum):
    CANNY = "canny"
    DEPTH = "depth"
    POSE = "pose"
    IP_ADAPTER = "ip-adapter"
    REFERENCE = "reference"


class GenerationRequest(BaseModel):
    """Normalized request every backend understands."""

    prompt: str = ""
    negative_prompt: str = ""
    model_hint: str | None = Field(default=None, description="Logical model name, e.g. 'flux-dev', 'sd35-large'.")
    width: int = 1024
    height: int = 1024
    seed: int | None = None
    steps: int | None = None
    guidance_scale: float | None = None
    num_outputs: int = 1

    # Image inputs (paths on disk); engines upload/encode as needed.
    image: Path | None = None
    mask: Path | None = None
    control_image: Path | None = None
    control_type: ControlType | None = None
    strength: float | None = Field(default=None, description="Denoise / control strength, 0..1.")

    # Video-specific
    duration_seconds: float | None = None
    fps: int | None = None
    interpolation_factor: int | None = Field(default=None, description="Frame-interpolation multiplier (2 = double fps).")

    # Upscale-specific
    upscale_factor: int | None = None

    extra: dict[str, Any] = Field(default_factory=dict, description="Backend-specific escape hatch.")


class GenerationResult(BaseModel):
    """Normalized result: remote URLs and/or local files, plus provenance."""

    provider: str
    model_id: str
    urls: list[str] = Field(default_factory=list)
    files: list[Path] = Field(default_factory=list)
    seed: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class BaseEngine(ABC):
    """Contract every backend engine implements.

    Subclasses declare ``name`` and ``supported_tasks`` and override the
    task methods they support; unsupported tasks raise ``TaskNotSupported``
    so the APIManager can fall through to the next backend.
    """

    name: ClassVar[str]
    supported_tasks: ClassVar[frozenset[Task]] = frozenset()

    def __init__(self, settings: AuraGenSettings) -> None:
        self.settings = settings

    @abstractmethod
    def is_configured(self) -> bool:
        """True when credentials + SDK are present and the engine is usable."""

    def supports(self, task: Task) -> bool:
        return task in self.supported_tasks

    def run(self, task: Task, request: GenerationRequest) -> GenerationResult:
        if not self.supports(task):
            raise TaskNotSupported(f"{self.name} does not support {task.value}")
        handler = getattr(self, task.value)
        return handler(request)

    # --- Task methods: override the ones the backend supports ----------
    def text_to_image(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support text_to_image")

    def text_to_video(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support text_to_video")

    def image_to_video(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support image_to_video")

    def inpaint(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support inpaint")

    def outpaint(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support outpaint")

    def control(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support control")

    def upscale(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support upscale")

    def interpolate(self, request: GenerationRequest) -> GenerationResult:
        raise TaskNotSupported(f"{self.name} does not support interpolate")
