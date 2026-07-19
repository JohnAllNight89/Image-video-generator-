"""High-level production engines.

* GenEngine     — quality-first image & video generation
* EditEngine    — inpainting / outpainting with masks
* DesignEngine  — logo & branding with strict composition rules
* ControlEngine — ControlNet / IP-Adapter / reference-guided generation

Each pipeline merges the active brand preset into the request, executes it
through the APIManager fallback chain, persists outputs into an organized
run folder and records reproducibility metadata.
"""

from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console

from auragen.config.settings import AuraGenSettings, BrandBook, BrandPreset
from auragen.engines.base import ControlType, GenerationRequest, GenerationResult, Task
from auragen.utils.api_manager import APIManager
from auragen.utils.image_utils import (
    download_file,
    guess_extension,
    move_into,
    prepare_outpaint_canvas,
    upscale_local,
)
from auragen.utils.metadata import HistoryStore, RunRecord


class PipelineResult:
    """What the CLI gets back: local files + the recorded metadata."""

    def __init__(self, files: list[Path], record: RunRecord, run_dir: Path) -> None:
        self.files = files
        self.record = record
        self.run_dir = run_dir


class BasePipeline:
    command: str = "generate"

    def __init__(
        self,
        manager: APIManager,
        settings: AuraGenSettings,
        brand: BrandBook,
        console: Console | None = None,
    ) -> None:
        self.manager = manager
        self.settings = settings
        self.brand = brand
        self.console = console or Console()
        self.history = HistoryStore(settings.output_dir)

    # --- Brand composition ---------------------------------------------
    def preset(self, style: str | None) -> tuple[str, BrandPreset]:
        name = style or self.settings.default_style
        return name, self.brand.get(name)

    def compose_prompt(self, prompt: str, preset: BrandPreset) -> str:
        return f"{prompt}, {preset.style_suffix}" if preset.style_suffix else prompt

    def compose_negative(self, preset: BrandPreset, extra: str | None = None) -> str:
        parts = [p for p in (preset.negative_prompt, self.brand.global_negative, extra) if p]
        return ", ".join(parts)

    def apply_preset_params(self, request: GenerationRequest, preset: BrandPreset) -> None:
        if request.guidance_scale is None:
            request.guidance_scale = preset.guidance_scale
        if request.steps is None:
            request.steps = preset.steps
        if request.model_hint is None:
            request.model_hint = preset.preferred_model

    # --- Execution + persistence ---------------------------------------
    def execute(
        self,
        task: Task,
        request: GenerationRequest,
        style_name: str | None,
        label: str | None = None,
    ) -> PipelineResult:
        started = time.monotonic()
        result = self.manager.execute(task, request)
        elapsed = time.monotonic() - started

        run_dir = self.history.new_run_dir(label or request.prompt or task.value)
        files = self._persist(result, run_dir, task)

        record = RunRecord(
            command=self.command,
            task=task.value,
            prompt=request.prompt,
            negative_prompt=request.negative_prompt,
            style=style_name,
            provider=result.provider,
            model_id=result.model_id,
            seed=result.seed if result.seed is not None else request.seed,
            params=request.model_dump(
                exclude={"prompt", "negative_prompt", "seed"},
                exclude_none=True,
                mode="json",
            ),
            files=[str(f) for f in files],
            duration_seconds=round(elapsed, 2),
        )
        self.history.save(record, run_dir)
        return PipelineResult(files, record, run_dir)

    def _persist(self, result: GenerationResult, run_dir: Path, task: Task) -> list[Path]:
        is_video = task in (Task.TEXT_TO_VIDEO, Task.IMAGE_TO_VIDEO, Task.INTERPOLATE)
        default_ext = ".mp4" if is_video else ".png"
        files: list[Path] = []
        for index, url in enumerate(result.urls, start=1):
            target = run_dir / f"{task.value}_{index:02d}{guess_extension(url, default_ext)}"
            files.append(download_file(url, target))
        for index, temp_file in enumerate(result.files, start=len(files) + 1):
            target = run_dir / f"{task.value}_{index:02d}{temp_file.suffix or default_ext}"
            files.append(move_into(temp_file, target))
        return files


class GenEngine(BasePipeline):
    """High-quality image & video generation (Flux.1, SD3.5, LTX, Kling)."""

    command = "generate"

    def image(
        self,
        prompt: str,
        style: str | None = None,
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        steps: int | None = None,
        guidance_scale: float | None = None,
        model: str | None = None,
        count: int = 1,
        negative: str | None = None,
    ) -> PipelineResult:
        style_name, preset = self.preset(style)
        request = GenerationRequest(
            prompt=self.compose_prompt(prompt, preset),
            negative_prompt=self.compose_negative(preset, negative),
            width=width,
            height=height,
            seed=seed,
            steps=steps,
            guidance_scale=guidance_scale,
            model_hint=model,
            num_outputs=count,
        )
        self.apply_preset_params(request, preset)
        return self.execute(Task.TEXT_TO_IMAGE, request, style_name, label=prompt)

    def video(
        self,
        prompt: str,
        style: str | None = None,
        image: Path | None = None,
        duration: float | None = None,
        seed: int | None = None,
        negative: str | None = None,
        interpolate: int | None = None,
    ) -> PipelineResult:
        """Text- or image-to-video with temporal-consistency guardrails.

        A fixed seed plus explicit motion-stability phrasing in the prompt
        and anti-flicker terms in the negative prompt measurably reduce
        shimmer; optional FILM interpolation (``interpolate``) then raises
        effective FPS for smoother motion.
        """
        style_name, preset = self.preset(style)
        stability = "smooth consistent motion, stable lighting, coherent subject across frames"
        anti_flicker = "flickering, strobing, jitter, morphing artifacts, temporal inconsistency, frame duplication"
        request = GenerationRequest(
            prompt=f"{self.compose_prompt(prompt, preset)}, {stability}",
            negative_prompt=self.compose_negative(preset, ", ".join(filter(None, [anti_flicker, negative]))),
            image=image,
            duration_seconds=duration,
            seed=seed,
        )
        task = Task.IMAGE_TO_VIDEO if image else Task.TEXT_TO_VIDEO
        result = self.execute(task, request, style_name, label=prompt)

        if interpolate and interpolate >= 2 and result.files:
            self.console.log(f"[cyan]Interpolating frames ×{interpolate} for smoother motion[/cyan]")
            try:
                smooth = self.execute(
                    Task.INTERPOLATE,
                    GenerationRequest(image=result.files[0], interpolation_factor=interpolate),
                    style_name,
                    label=f"{prompt} interpolated",
                )
                result.files.extend(smooth.files)
            except Exception as exc:
                self.console.log(f"[yellow]Frame interpolation unavailable ({exc}); keeping original video[/yellow]")
        return result


class EditEngine(BasePipeline):
    """Inpainting, masking and outpainting."""

    command = "edit"

    def inpaint(
        self,
        image: Path,
        mask: Path,
        prompt: str,
        style: str | None = None,
        strength: float | None = None,
        seed: int | None = None,
        negative: str | None = None,
    ) -> PipelineResult:
        style_name, preset = self.preset(style)
        request = GenerationRequest(
            prompt=self.compose_prompt(prompt, preset),
            negative_prompt=self.compose_negative(preset, negative),
            image=image,
            mask=mask,
            strength=strength,
            seed=seed,
        )
        self.apply_preset_params(request, preset)
        return self.execute(Task.INPAINT, request, style_name, label=prompt)

    def outpaint(
        self,
        image: Path,
        prompt: str,
        pad: tuple[int, int, int, int],
        style: str | None = None,
        seed: int | None = None,
        negative: str | None = None,
    ) -> PipelineResult:
        style_name, preset = self.preset(style)
        workdir = self.settings.output_dir / ".work"
        padded, mask = prepare_outpaint_canvas(image, *pad, workdir=workdir)
        request = GenerationRequest(
            prompt=self.compose_prompt(prompt, preset),
            negative_prompt=self.compose_negative(preset, negative),
            image=padded,
            mask=mask,
            seed=seed,
        )
        self.apply_preset_params(request, preset)
        return self.execute(Task.OUTPAINT, request, style_name, label=prompt)


class DesignEngine(BasePipeline):
    """Logo / branding generation with strict composition discipline.

    Quality and consistency over speed: high step counts, elevated
    guidance, square canvases, multiple seed-varied candidates, and an
    aggressive negative prompt to suppress hallucinated text, gradients
    and clutter.
    """

    command = "design"

    # Non-negotiable composition rules appended to every design prompt.
    COMPOSITION_RULES = (
        "single centered logomark, balanced symmetrical composition, "
        "flat solid background, strong silhouette readable at small sizes"
    )
    # Hallucination suppressors applied on top of the preset's negatives.
    STRICT_NEGATIVE = (
        "text, letters, words, typography, gibberish characters, misspelling, "
        "photorealistic detail, photograph, 3d render, shadows, reflections, "
        "multiple marks, collage, mockup, watermark, noisy background"
    )

    def logo(
        self,
        prompt: str,
        style: str | None = "minimalist-logo",
        variations: int = 4,
        size: int = 1024,
        seed: int | None = None,
        negative: str | None = None,
    ) -> PipelineResult:
        style_name, preset = self.preset(style)
        request = GenerationRequest(
            prompt=f"{self.compose_prompt(prompt, preset)}, {self.COMPOSITION_RULES}",
            negative_prompt=self.compose_negative(
                preset, ", ".join(filter(None, [self.STRICT_NEGATIVE, negative]))
            ),
            width=size,
            height=size,
            seed=seed,
            num_outputs=max(1, variations),
        )
        self.apply_preset_params(request, preset)
        # Design work is deliberately slow and precise.
        request.steps = max(request.steps or 0, 50)
        if request.guidance_scale is None or request.guidance_scale < 6.0:
            request.guidance_scale = 7.0
        return self.execute(Task.TEXT_TO_IMAGE, request, style_name, label=prompt)


class ControlEngine(BasePipeline):
    """ControlNet / IP-Adapter / reference-image guided generation."""

    command = "control"

    def guided(
        self,
        prompt: str,
        reference: Path,
        control_type: ControlType = ControlType.REFERENCE,
        strength: float = 0.6,
        style: str | None = None,
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        negative: str | None = None,
    ) -> PipelineResult:
        style_name, preset = self.preset(style)
        request = GenerationRequest(
            prompt=self.compose_prompt(prompt, preset),
            negative_prompt=self.compose_negative(preset, negative),
            control_image=reference,
            control_type=control_type,
            strength=strength,
            width=width,
            height=height,
            seed=seed,
        )
        self.apply_preset_params(request, preset)
        return self.execute(Task.CONTROL, request, style_name, label=prompt)


class UpscalePipeline(BasePipeline):
    """API upscaling with a local Lanczos fallback (graceful degradation)."""

    command = "upscale"

    def upscale(self, image: Path, factor: int = 2) -> PipelineResult:
        request = GenerationRequest(image=image, upscale_factor=factor)
        try:
            return self.execute(Task.UPSCALE, request, None, label=f"upscale {image.stem}")
        except Exception as exc:
            self.console.log(f"[yellow]API upscaling unavailable ({exc}); using local Lanczos fallback[/yellow]")
            run_dir = self.history.new_run_dir(f"upscale {image.stem}")
            local = upscale_local(image, factor, run_dir / f"{image.stem}_x{factor}{image.suffix}")
            record = RunRecord(
                command=self.command,
                task=Task.UPSCALE.value,
                prompt=f"local lanczos x{factor} of {image}",
                provider="local",
                model_id="pillow/lanczos+unsharp",
                params={"upscale_factor": factor},
                files=[str(local)],
            )
            self.history.save(record, run_dir)
            return PipelineResult([local], record, run_dir)
