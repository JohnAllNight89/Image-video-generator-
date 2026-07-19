"""Local ComfyUI backend — last resort / air-gapped option.

Talks to a running ComfyUI server over its HTTP API: queue a workflow via
``POST /prompt``, poll ``GET /history/{id}``, then download outputs via
``GET /view``. Ships a minimal SDXL-style txt2img workflow; power users can
point AURAGEN_COMFY_WORKFLOW at their own exported (API-format) workflow
containing ``%%PROMPT%%`` / ``%%NEGATIVE%%`` / ``%%SEED%%`` placeholders.
"""

from __future__ import annotations

import json
import os
import random
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, ClassVar

import httpx

from auragen.engines.base import (
    BaseEngine,
    EngineError,
    EngineNotConfigured,
    GenerationRequest,
    GenerationResult,
    Task,
)

_DEFAULT_WORKFLOW = """
{
  "3": {"class_type": "KSampler", "inputs": {"seed": %%SEED%%, "steps": %%STEPS%%,
        "cfg": %%CFG%%, "sampler_name": "euler", "scheduler": "normal", "denoise": 1,
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
  "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
  "5": {"class_type": "EmptyLatentImage", "inputs": {"width": %%WIDTH%%, "height": %%HEIGHT%%, "batch_size": 1}},
  "6": {"class_type": "CLIPTextEncode", "inputs": {"text": %%PROMPT%%, "clip": ["4", 1]}},
  "7": {"class_type": "CLIPTextEncode", "inputs": {"text": %%NEGATIVE%%, "clip": ["4", 1]}},
  "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
  "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "auragen", "images": ["8", 0]}}
}
"""


class ComfyUIEngine(BaseEngine):
    name: ClassVar[str] = "comfyui"
    supported_tasks: ClassVar[frozenset[Task]] = frozenset({Task.TEXT_TO_IMAGE})

    def is_configured(self) -> bool:
        try:
            response = httpx.get(f"{self.settings.comfy_url}/system_stats", timeout=2.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def _workflow(self, request: GenerationRequest) -> dict[str, Any]:
        template_path = os.environ.get("AURAGEN_COMFY_WORKFLOW")
        template = Path(template_path).read_text(encoding="utf-8") if template_path else _DEFAULT_WORKFLOW
        seed = request.seed if request.seed is not None else random.randint(0, 2**31 - 1)
        rendered = (
            template.replace("%%PROMPT%%", json.dumps(request.prompt))
            .replace("%%NEGATIVE%%", json.dumps(request.negative_prompt))
            .replace("%%SEED%%", str(seed))
            .replace("%%STEPS%%", str(request.steps or 30))
            .replace("%%CFG%%", str(request.guidance_scale or 7.0))
            .replace("%%WIDTH%%", str(request.width))
            .replace("%%HEIGHT%%", str(request.height))
        )
        return json.loads(rendered)

    def text_to_image(self, request: GenerationRequest) -> GenerationResult:
        base = self.settings.comfy_url
        client_id = uuid.uuid4().hex
        try:
            queued = httpx.post(
                f"{base}/prompt",
                json={"prompt": self._workflow(request), "client_id": client_id},
                timeout=10.0,
            )
            queued.raise_for_status()
            prompt_id = queued.json()["prompt_id"]
        except httpx.HTTPError as exc:
            raise EngineNotConfigured(f"ComfyUI server unreachable at {base}: {exc}") from exc

        deadline = time.monotonic() + self.settings.request_timeout_seconds
        outputs: dict[str, Any] = {}
        while time.monotonic() < deadline:
            history = httpx.get(f"{base}/history/{prompt_id}", timeout=10.0).json()
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise EngineError(f"ComfyUI workflow failed: {status}")
                outputs = entry.get("outputs", {})
                if outputs:
                    break
            time.sleep(1.0)
        else:
            raise EngineError("ComfyUI generation timed out")

        files: list[Path] = []
        for node_output in outputs.values():
            for image_info in node_output.get("images", []):
                params = {
                    "filename": image_info["filename"],
                    "subfolder": image_info.get("subfolder", ""),
                    "type": image_info.get("type", "output"),
                }
                data = httpx.get(f"{base}/view", params=params, timeout=30.0).content
                handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="auragen_comfy_")
                Path(handle.name).write_bytes(data)
                files.append(Path(handle.name))

        if not files:
            raise EngineError("ComfyUI returned no images")
        return GenerationResult(provider=self.name, model_id="comfyui/local-workflow", files=files, seed=request.seed)
