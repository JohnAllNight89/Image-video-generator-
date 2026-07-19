"""AuraGen CLI — Typer + Rich frontend over the pipeline engines."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from auragen import __app_name__, __version__
from auragen.config.settings import EngineName, get_settings, load_brand_book
from auragen.engines.base import ControlType, EngineError
from auragen.engines.pipelines import (
    BasePipeline,
    ControlEngine,
    DesignEngine,
    EditEngine,
    GenEngine,
    PipelineResult,
    UpscalePipeline,
)
from auragen.utils.api_manager import APIManager
from auragen.utils.image_utils import parse_size
from auragen.utils.metadata import HistoryStore

app = typer.Typer(
    name="auragen",
    help=f"[bold magenta]{__app_name__}[/bold magenta] — media production suite for The Unified Spirit.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
edit_app = typer.Typer(help="Inpainting, masking and outpainting.", no_args_is_help=True)
app.add_typer(edit_app, name="edit")

console = Console()

# Shared option: pin a single backend engine for this invocation.
EngineOption = typer.Option(None, "--engine", "-e", help="Pin one backend (fal, replicate, huggingface, comfyui); disables fallback.")
StyleOption = typer.Option(None, "--style", "-s", help="Brand preset from brand.json (see `auragen styles`).")
SeedOption = typer.Option(None, "--seed", help="Seed for reproducible output.")
NegativeOption = typer.Option(None, "--negative", help="Extra negative prompt fragments.")


def _build(pipeline_cls: type[BasePipeline], engine: Optional[EngineName]) -> BasePipeline:
    settings = get_settings()
    brand = load_brand_book()
    manager = APIManager(settings, console=console, engine_override=engine)
    return pipeline_cls(manager, settings, brand, console=console)


def _run(description: str, func, *args, **kwargs) -> PipelineResult:
    with Progress(
        SpinnerColumn(style="magenta"),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        progress.add_task(description, total=None)
        try:
            return func(*args, **kwargs)
        except EngineError as exc:
            progress.stop()
            console.print(Panel(str(exc), title="[red]Generation failed[/red]", border_style="red"))
            raise typer.Exit(code=1) from exc


def _report(result: PipelineResult) -> None:
    record = result.record
    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_row("[bold]Provider[/bold]", f"{record.provider} · {record.model_id}")
    if record.style:
        table.add_row("[bold]Style[/bold]", record.style)
    if record.seed is not None:
        table.add_row("[bold]Seed[/bold]", str(record.seed))
    if record.duration_seconds:
        table.add_row("[bold]Time[/bold]", f"{record.duration_seconds:.1f}s")
    table.add_row("[bold]Run dir[/bold]", str(result.run_dir))
    for file in result.files:
        table.add_row("[bold green]Output[/bold green]", str(file))
    console.print(Panel(table, title=f"[green]✓ {record.task}[/green]", border_style="green"))


@app.callback(invoke_without_command=True)
def _main(
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit."),
) -> None:
    if version:
        console.print(f"{__app_name__} v{__version__}")
        raise typer.Exit()


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@app.command()
def generate(
    prompt: str = typer.Argument(..., help="What to create."),
    style: Optional[str] = StyleOption,
    size: str = typer.Option("1024x1024", "--size", help="WIDTHxHEIGHT, e.g. 1536x1024."),
    count: int = typer.Option(1, "--count", "-n", min=1, max=8, help="Number of images."),
    seed: Optional[int] = SeedOption,
    steps: Optional[int] = typer.Option(None, "--steps", help="Inference steps (preset default otherwise)."),
    guidance: Optional[float] = typer.Option(None, "--guidance", help="Guidance/CFG scale."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model hint: flux-dev, flux-schnell, flux-pro, sd35-large."),
    negative: Optional[str] = NegativeOption,
    upscale: bool = typer.Option(False, "--upscale", help="Upscale results ×2 after generation."),
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Generate high-quality images (GenEngine)."""
    width, height = parse_size(size)
    gen: GenEngine = _build(GenEngine, engine)  # type: ignore[assignment]
    result = _run(
        f"Generating {count} image(s)…",
        gen.image,
        prompt,
        style=style,
        width=width,
        height=height,
        seed=seed,
        steps=steps,
        guidance_scale=guidance,
        model=model,
        count=count,
        negative=negative,
    )
    _report(result)
    if upscale:
        upscaler: UpscalePipeline = _build(UpscalePipeline, engine)  # type: ignore[assignment]
        for file in list(result.files):
            _report(_run(f"Upscaling {file.name}…", upscaler.upscale, file, 2))


@app.command()
def video(
    prompt: str = typer.Argument(..., help="Motion/scene description."),
    style: Optional[str] = StyleOption,
    image: Optional[Path] = typer.Option(None, "--image", "-i", exists=True, help="Start frame → image-to-video."),
    duration: Optional[float] = typer.Option(5.0, "--duration", "-d", help="Target duration in seconds."),
    seed: Optional[int] = SeedOption,
    negative: Optional[str] = NegativeOption,
    interpolate: Optional[int] = typer.Option(
        None, "--interpolate", help="Frame-interpolation factor (2 = double FPS) to smooth motion."
    ),
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Generate video with temporal-consistency guardrails (GenEngine)."""
    gen: GenEngine = _build(GenEngine, engine)  # type: ignore[assignment]
    result = _run(
        "Generating video…",
        gen.video,
        prompt,
        style=style,
        image=image,
        duration=duration,
        seed=seed,
        negative=negative,
        interpolate=interpolate,
    )
    _report(result)


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------
@edit_app.command()
def inpaint(
    image: Path = typer.Argument(..., exists=True, help="Source image."),
    prompt: str = typer.Argument(..., help="What to paint into the masked area."),
    mask: Path = typer.Option(..., "--mask", exists=True, help="Mask image (white = repaint)."),
    style: Optional[str] = StyleOption,
    strength: Optional[float] = typer.Option(None, "--strength", min=0.0, max=1.0, help="Denoise strength."),
    seed: Optional[int] = SeedOption,
    negative: Optional[str] = NegativeOption,
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Repaint masked regions of an image (EditEngine)."""
    editor: EditEngine = _build(EditEngine, engine)  # type: ignore[assignment]
    _report(_run("Inpainting…", editor.inpaint, image, mask, prompt, style=style, strength=strength, seed=seed, negative=negative))


@edit_app.command()
def outpaint(
    image: Path = typer.Argument(..., exists=True, help="Source image."),
    prompt: str = typer.Argument(..., help="What the extended canvas should contain."),
    left: int = typer.Option(0, help="Pixels to extend left."),
    top: int = typer.Option(0, help="Pixels to extend up."),
    right: int = typer.Option(0, help="Pixels to extend right."),
    bottom: int = typer.Option(0, help="Pixels to extend down."),
    style: Optional[str] = StyleOption,
    seed: Optional[int] = SeedOption,
    negative: Optional[str] = NegativeOption,
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Extend an image beyond its borders (EditEngine)."""
    if not any((left, top, right, bottom)):
        console.print("[red]Specify at least one of --left/--top/--right/--bottom.[/red]")
        raise typer.Exit(code=2)
    editor: EditEngine = _build(EditEngine, engine)  # type: ignore[assignment]
    _report(_run("Outpainting…", editor.outpaint, image, prompt, (left, top, right, bottom), style=style, seed=seed, negative=negative))


# ---------------------------------------------------------------------------
# Design & control
# ---------------------------------------------------------------------------
@app.command()
def design(
    prompt: str = typer.Argument(..., help="Logo / brand-mark concept."),
    style: str = typer.Option("minimalist-logo", "--style", "-s", help="Brand preset (defaults to minimalist-logo)."),
    variations: int = typer.Option(4, "--variations", "-n", min=1, max=8, help="Seed-varied candidates to produce."),
    size: int = typer.Option(1024, "--size", help="Square canvas edge in pixels."),
    seed: Optional[int] = SeedOption,
    negative: Optional[str] = NegativeOption,
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Logo & branding generation with strict composition rules (DesignEngine)."""
    designer: DesignEngine = _build(DesignEngine, engine)  # type: ignore[assignment]
    _report(_run(f"Designing {variations} candidate(s)…", designer.logo, prompt, style=style, variations=variations, size=size, seed=seed, negative=negative))


@app.command()
def control(
    prompt: str = typer.Argument(..., help="What to generate."),
    ref: Path = typer.Option(..., "--ref", "-r", exists=True, help="Reference / control image."),
    control_type: ControlType = typer.Option(ControlType.REFERENCE, "--type", "-t", help="canny, depth, pose, ip-adapter, reference."),
    strength: float = typer.Option(0.6, "--strength", min=0.0, max=1.0, help="How strongly the reference constrains output."),
    style: Optional[str] = StyleOption,
    size: str = typer.Option("1024x1024", "--size", help="WIDTHxHEIGHT."),
    seed: Optional[int] = SeedOption,
    negative: Optional[str] = NegativeOption,
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Reference-guided generation via ControlNet / IP-Adapter (ControlEngine)."""
    width, height = parse_size(size)
    controller: ControlEngine = _build(ControlEngine, engine)  # type: ignore[assignment]
    _report(_run("Generating with reference guidance…", controller.guided, prompt, ref, control_type=control_type, strength=strength, style=style, width=width, height=height, seed=seed, negative=negative))


@app.command()
def upscale(
    image: Path = typer.Argument(..., exists=True, help="Image to upscale."),
    factor: int = typer.Option(2, "--factor", "-f", min=2, max=4, help="Upscale multiplier."),
    engine: Optional[EngineName] = EngineOption,
) -> None:
    """Upscale an image (API first, local Lanczos fallback)."""
    upscaler: UpscalePipeline = _build(UpscalePipeline, engine)  # type: ignore[assignment]
    _report(_run(f"Upscaling ×{factor}…", upscaler.upscale, image, factor))


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------
@app.command()
def history(
    limit: int = typer.Option(20, "--limit", "-l", help="Rows to show."),
    task: Optional[str] = typer.Option(None, "--task", help="Filter by task, e.g. text_to_image."),
) -> None:
    """Show recent generation runs (newest first)."""
    records = HistoryStore(get_settings().output_dir).load(limit=limit, task=task)
    if not records:
        console.print("[yellow]No history yet — generate something first.[/yellow]")
        return
    table = Table(title=f"{__app_name__} history", header_style="bold magenta")
    table.add_column("When", no_wrap=True)
    table.add_column("Task")
    table.add_column("Style")
    table.add_column("Provider")
    table.add_column("Seed", justify="right")
    table.add_column("Prompt", overflow="ellipsis", max_width=48)
    table.add_column("Files", justify="right")
    for record in records:
        table.add_row(
            record.created_at.strftime("%Y-%m-%d %H:%M"),
            record.task,
            record.style or "—",
            record.provider,
            str(record.seed) if record.seed is not None else "—",
            record.prompt,
            str(len(record.files)),
        )
    console.print(table)


@app.command()
def gallery(
    limit: int = typer.Option(12, "--limit", "-l", help="Runs to list."),
) -> None:
    """List output files from recent runs."""
    records = HistoryStore(get_settings().output_dir).load(limit=limit)
    if not records:
        console.print("[yellow]Gallery is empty — generate something first.[/yellow]")
        return
    for record in records:
        body = "\n".join(record.files) or "(no files recorded)"
        console.print(
            Panel(
                body,
                title=f"[bold]{record.prompt[:60] or record.task}[/bold]",
                subtitle=f"{record.created_at.strftime('%Y-%m-%d %H:%M')} · {record.provider} · {record.task}",
                border_style="magenta",
            )
        )


@app.command()
def styles() -> None:
    """List brand presets from brand.json."""
    brand = load_brand_book()
    table = Table(title=f"{brand.brand_name} — brand presets", header_style="bold magenta")
    table.add_column("Preset", style="bold")
    table.add_column("Description")
    table.add_column("Model")
    table.add_column("Steps", justify="right")
    table.add_column("CFG", justify="right")
    for name, preset in brand.presets.items():
        table.add_row(
            name,
            preset.description,
            preset.preferred_model or "—",
            str(preset.steps) if preset.steps else "—",
            f"{preset.guidance_scale:g}" if preset.guidance_scale else "—",
        )
    console.print(table)


@app.command()
def doctor() -> None:
    """Check which backend engines are configured and reachable."""
    settings = get_settings()
    manager = APIManager(settings, console=console)
    table = Table(title="Engine status", header_style="bold magenta")
    table.add_column("Engine", style="bold")
    table.add_column("Status")
    table.add_column("Notes")
    notes = {
        "fal": "set FAL_KEY in .env",
        "replicate": "set REPLICATE_API_TOKEN in .env",
        "huggingface": "set HF_TOKEN in .env",
        "comfyui": f"server expected at {settings.comfy_url}",
    }
    for name, ok in manager.engine_status().items():
        status = "[green]● ready[/green]" if ok else "[red]○ unavailable[/red]"
        table.add_row(name, status, "" if ok else notes.get(name, ""))
    console.print(table)
    console.print(f"Output dir: [bold]{settings.output_dir.resolve()}[/bold]  ·  Brand file: [bold]{settings.brand_file}[/bold]")
