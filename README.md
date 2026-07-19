# 🎨 Image & Video Generator

> **New:** this repo now also ships **[AuraGen](#-auragen--media-production-suite)** — a production-grade Python CLI
> for The Unified Spirit with multi-provider AI generation, editing, branding and video tooling.

A free, unlimited image and video generator that runs entirely in your browser.
No API key, no sign-up, no usage caps, no watermarks.

## What's included

| Tool | What it does |
|------|--------------|
| **Web app** (`index.html`) | Generate AI images and render videos, right in the browser |
| **Prompt CLI** (`generator.py`) | Standalone Python tool that crafts polished, reusable prompts for any AI generator (Midjourney, Kling, Runway, etc.) |

## Web app features

### 🖼️ Image generation
- Powered by the free [Pollinations.ai](https://pollinations.ai) API — no key required
- **Flux** (quality) and **Turbo** (speed) models
- Any resolution up to 4096×4096, with presets for square, landscape, portrait, and Full HD
- Batch generation — up to 12 images per click
- Seed control for reproducible results
- Optional automatic prompt enhancement

### 🎬 Video generation
Videos are rendered locally in your browser (canvas + MediaRecorder) and exported as WebM:
- **AI animation** — generates a sequence of keyframes from your prompt and blends them into a video
- **Slideshow** — turns your gallery images into a video
- Motion effects: Ken Burns (pan & zoom), slow zoom, or crossfade
- 720p / 1080p / portrait / square output, 24–60 FPS

### 📁 Gallery
- Every generated image is collected automatically
- Select images for slideshow videos, bulk download, or deletion
- Full-size lightbox viewer with one-click download

## Getting started

### Web app
No build step, no dependencies. Either:

```bash
# Just open the file
open index.html

# Or serve it locally
python3 -m http.server 8000
# then visit http://localhost:8000
```

It also works as-is on GitHub Pages: **Settings → Pages → Deploy from branch**.

### Prompt CLI

```bash
python3 generator.py
```

Follow the prompts to build image or video prompts. Your style preferences are
stored in `brand.json` (created on first run) — edit it to customize the default
look applied to every prompt.

## Notes

- The web app talks only to the Pollinations image API; videos never leave your machine.
- Generated content is subject to the upstream model provider's policies.

---

# ✨ AuraGen — media production suite

A professional, production-ready CLI for **The Unified Spirit**: image & video
generation (Flux.1, SD3.5, Kling, LTX), inpainting/outpainting, logo & branding
design, ControlNet / IP-Adapter reference guidance — with automatic fallback
across Fal.ai → Replicate → Hugging Face → local ComfyUI.

## Installation

```bash
# From the repo root (Python 3.10+)
pip install -e ".[all]"        # core + all provider SDKs
# or minimal core only:
pip install -e .

# Configure credentials (any subset works — AuraGen falls back in order)
cp .env.example .env           # then fill in FAL_KEY / REPLICATE_API_TOKEN / HF_TOKEN
auragen doctor                 # verify which engines are ready
```

## Usage

```bash
# Images (GenEngine) — brand presets via --style
auragen generate "a lighthouse at dawn" --style cinematic --size 1536x1024 -n 2
auragen generate "product shot of a ceramic mug" --style photorealistic --seed 42 --upscale

# Video (GenEngine) — temporal-consistency guardrails + optional frame interpolation
auragen video "slow dolly through a misty forest" --style cinematic --interpolate 2
auragen video "gentle camera orbit" --image hero.png --duration 5

# Editing (EditEngine)
auragen edit inpaint photo.png "a red vintage car" --mask mask.png
auragen edit outpaint photo.png "rolling hills continue" --left 256 --right 256

# Logos & branding (DesignEngine) — strict composition rules, anti-hallucination negatives
auragen design "abstract dove rising from interlocking circles" --variations 4

# Reference-guided generation (ControlEngine)
auragen control "same pose, silver sculpture" --ref pose.png --type pose --strength 0.7
auragen control "match this style" --ref moodboard.png --type ip-adapter

# Utilities
auragen upscale image.png --factor 2      # API upscale, local Lanczos fallback
auragen styles                            # list brand presets
auragen history --limit 20                # past runs with seeds & providers
auragen gallery                           # output files per run
auragen doctor                            # engine/credential status
```

Every run lands in `outputs/YYYY-MM-DD/HHMMSS_prompt-slug/` with a
`metadata.json` sidecar (prompt, negative prompt, model, provider, seed,
parameters, timing) and is indexed in `outputs/history.jsonl`.

Brand presets live in `auragen/config/brand.json` (photorealistic, cinematic,
minimalist-logo, luxury, ethereal, vibrant-social) — edit them or point
`AURAGEN_BRAND_FILE` at your own book. Pin a backend with `--engine fal` or
`AURAGEN_ENGINE`, and reorder fallback with `AURAGEN_ENGINE_ORDER`.

## API stack choice

- **Fal.ai first** — one SDK covers best-in-class endpoints for Flux.1
  dev/schnell/pro, SD3.5, inpainting, ControlNet/IP-Adapter (flux-general),
  Kling & LTX video, clarity upscaling and FILM frame interpolation, with low
  cold-start latency. That breadth means most tasks never need a second
  provider.
- **Replicate second** — near-identical model coverage (Flux fill/canny/depth/
  redux, SD3.5, Real-ESRGAN, LTX) under a different quota pool, so a Fal rate
  limit doesn't stop production.
- **Hugging Face Inference third** — text-to-image safety net on a third,
  independent quota.
- **ComfyUI last** — a local, air-gapped escape hatch: bring your own
  checkpoints and exported API workflows (`AURAGEN_COMFY_WORKFLOW`), zero
  cloud dependency.

Rate limits are retried with exponential backoff before falling through the
chain; secrets come exclusively from `.env` / environment variables.
