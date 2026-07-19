# 🎨 Image & Video Generator

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
