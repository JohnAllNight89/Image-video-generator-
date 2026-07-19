"""Image/video helpers: downloads, canvas prep for outpainting, local
upscaling fallback, and frame-level video smoothing utilities."""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

import httpx
from PIL import Image, ImageFilter


def slugify(text: str, max_length: int = 48) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "untitled"


def guess_extension(url: str, default: str = ".png") -> str:
    path = httpx.URL(url).path.lower()
    for ext in (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".gif"):
        if path.endswith(ext):
            return ext
    return default


def download_file(url: str, destination: Path, retries: int = 3) -> Path:
    """Stream a result URL to disk with basic retry."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as response:
                response.raise_for_status()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            return destination
        except httpx.HTTPError as exc:
            last_error = exc
            time.sleep(2**attempt)
    raise RuntimeError(f"Failed to download {url}: {last_error}")


def move_into(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    return destination


def parse_size(value: str) -> tuple[int, int]:
    """Parse '1024x1024' → (1024, 1024)."""
    match = re.fullmatch(r"(\d+)\s*[xX×]\s*(\d+)", value.strip())
    if not match:
        raise ValueError(f"Invalid size '{value}' — expected WIDTHxHEIGHT, e.g. 1024x1024")
    return int(match.group(1)), int(match.group(2))


def upscale_local(image_path: Path, factor: int = 2, output_path: Path | None = None) -> Path:
    """CPU-only Lanczos upscale with light sharpening — the graceful
    degradation path when no upscaling API is reachable."""
    image = Image.open(image_path)
    upscaled = image.resize((image.width * factor, image.height * factor), Image.LANCZOS)
    upscaled = upscaled.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=3))
    target = output_path or image_path.with_name(f"{image_path.stem}_x{factor}{image_path.suffix}")
    upscaled.save(target)
    return target


def prepare_outpaint_canvas(
    image_path: Path,
    pad_left: int,
    pad_top: int,
    pad_right: int,
    pad_bottom: int,
    workdir: Path,
) -> tuple[Path, Path]:
    """Build the padded image + border mask so outpainting can reuse the
    inpainting endpoints. White mask areas are regions to synthesize."""
    workdir.mkdir(parents=True, exist_ok=True)
    image = Image.open(image_path).convert("RGB")
    new_size = (image.width + pad_left + pad_right, image.height + pad_top + pad_bottom)

    canvas = Image.new("RGB", new_size, (127, 127, 127))
    canvas.paste(image, (pad_left, pad_top))

    mask = Image.new("L", new_size, 255)
    # Keep the original pixels: black = preserve. Slight inset + blur feathers the seam.
    inset = 8
    keep_box = (
        pad_left + inset,
        pad_top + inset,
        pad_left + image.width - inset,
        pad_top + image.height - inset,
    )
    mask.paste(0, keep_box)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=6))

    padded_path = workdir / f"{image_path.stem}_padded.png"
    mask_path = workdir / f"{image_path.stem}_outpaint_mask.png"
    canvas.save(padded_path)
    mask.save(mask_path)
    return padded_path, mask_path


# ---------------------------------------------------------------------------
# Video smoothing: temporal consistency + frame interpolation (local fallback)
# ---------------------------------------------------------------------------

def temporal_smooth_frames(frames: list[Image.Image], blend: float = 0.25) -> list[Image.Image]:
    """Reduce flicker with an exponential moving average across frames.

    Each output frame is (1-blend)*current + blend*previous_smoothed, which
    damps high-frequency luminance/color jitter between consecutive frames
    while preserving genuine motion. ``blend`` of 0.2–0.35 works well.
    """
    if not frames:
        return []
    smoothed = [frames[0]]
    for frame in frames[1:]:
        previous = smoothed[-1]
        if frame.size != previous.size:
            frame = frame.resize(previous.size, Image.LANCZOS)
        smoothed.append(Image.blend(frame.convert("RGB"), previous.convert("RGB"), blend))
    return smoothed


def interpolate_frames(frames: list[Image.Image], factor: int = 2) -> list[Image.Image]:
    """Insert cross-blended in-between frames to raise effective FPS.

    A pure-Python stand-in for optical-flow interpolation (FILM/RIFE): when
    the Fal FILM endpoint is unavailable this still smooths perceived motion
    for slideshow-style or low-motion clips.
    """
    if factor < 2 or len(frames) < 2:
        return list(frames)
    result: list[Image.Image] = []
    for current, upcoming in zip(frames, frames[1:]):
        result.append(current)
        upcoming_rgb = upcoming.convert("RGB").resize(current.size)
        for step in range(1, factor):
            result.append(Image.blend(current.convert("RGB"), upcoming_rgb, step / factor))
    result.append(frames[-1])
    return result
