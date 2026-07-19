"""Runtime configuration for AuraGen.

Secrets are read from the environment / a local ``.env`` file via
python-dotenv + pydantic-settings. Nothing is ever hardcoded here.

Provider SDKs (fal_client, replicate, huggingface_hub) read their own
canonical variables (``FAL_KEY``, ``REPLICATE_API_TOKEN``, ``HF_TOKEN``),
so we call ``load_dotenv()`` at import time to populate ``os.environ``
before any of those SDKs are imported.
"""

from __future__ import annotations

import json
from enum import Enum
from functools import lru_cache
from pathlib import Path

from dotenv import find_dotenv, load_dotenv
from pydantic import AliasChoices, BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Populate os.environ from .env so downstream SDKs see the keys too.
load_dotenv(find_dotenv(usecwd=True))

_PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_BRAND_FILE = _PACKAGE_DIR / "brand.json"


class EngineName(str, Enum):
    """Backend engines AuraGen can route work to."""

    FAL = "fal"
    REPLICATE = "replicate"
    HUGGINGFACE = "huggingface"
    COMFYUI = "comfyui"


class AuraGenSettings(BaseSettings):
    """All runtime settings, overridable via env vars or ``.env``.

    ``AURAGEN_``-prefixed variables always work; the API keys also accept
    their canonical provider names (``FAL_KEY`` etc.).
    """

    model_config = SettingsConfigDict(
        env_prefix="AURAGEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Credentials (never hardcoded, never logged) -------------------
    fal_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("FAL_KEY", "AURAGEN_FAL_KEY"),
        description="Fal.ai API key (id:secret).",
    )
    replicate_api_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REPLICATE_API_TOKEN", "AURAGEN_REPLICATE_API_TOKEN"),
        description="Replicate API token.",
    )
    hf_token: str | None = Field(
        default=None,
        validation_alias=AliasChoices("HF_TOKEN", "HUGGINGFACE_TOKEN", "AURAGEN_HF_TOKEN"),
        description="Hugging Face Inference API token.",
    )

    # --- Engine routing ------------------------------------------------
    engine_order: list[EngineName] = Field(
        default=[EngineName.FAL, EngineName.REPLICATE, EngineName.HUGGINGFACE, EngineName.COMFYUI],
        description="Fallback priority: first configured engine that supports the task wins.",
    )
    engine: EngineName | None = Field(
        default=None,
        description="Pin every task to a single engine (disables fallback).",
    )
    comfy_url: str = Field(
        default="http://127.0.0.1:8188",
        description="Base URL of a local ComfyUI server.",
    )

    # --- Output & brand ------------------------------------------------
    output_dir: Path = Field(default=Path("outputs"), description="Root folder for generated media.")
    brand_file: Path = Field(default=DEFAULT_BRAND_FILE, description="Path to brand.json presets.")
    default_style: str = Field(default="photorealistic", description="Brand preset used when --style is omitted.")

    # --- Behaviour -----------------------------------------------------
    max_retries_per_engine: int = Field(default=2, ge=0, le=10)
    retry_backoff_seconds: float = Field(default=2.0, gt=0)
    request_timeout_seconds: float = Field(default=600.0, gt=0)

    @field_validator("engine_order", mode="before")
    @classmethod
    def _split_engine_order(cls, value: object) -> object:
        # Allow AURAGEN_ENGINE_ORDER="fal,replicate" style values.
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def configured_key_for(self, engine: EngineName) -> str | None:
        return {
            EngineName.FAL: self.fal_key,
            EngineName.REPLICATE: self.replicate_api_token,
            EngineName.HUGGINGFACE: self.hf_token,
            EngineName.COMFYUI: self.comfy_url,
        }[engine]


class BrandPreset(BaseModel):
    """One entry in brand.json: a reusable visual identity recipe."""

    description: str = ""
    style_suffix: str = Field(..., description="Appended to every prompt using this preset.")
    negative_prompt: str = Field(default="", description="Base negative prompt for this preset.")
    guidance_scale: float | None = Field(default=None, description="Override CFG/guidance for this preset.")
    steps: int | None = Field(default=None, description="Override inference steps for this preset.")
    preferred_model: str | None = Field(
        default=None,
        description="Logical model hint (e.g. 'flux-dev', 'sd35-large') the engines map to concrete model ids.",
    )
    aspect_ratio: str | None = Field(default=None, description="Default aspect ratio, e.g. '1:1', '16:9'.")

    def merge_negative(self, extra: str | None) -> str:
        parts = [p for p in (self.negative_prompt, extra) if p]
        return ", ".join(parts)


class BrandBook(BaseModel):
    """The whole brand.json document."""

    brand_name: str = "The Unified Spirit"
    tagline: str = ""
    global_negative: str = Field(
        default="",
        description="Negative prompt fragments applied to every generation regardless of preset.",
    )
    presets: dict[str, BrandPreset]

    def get(self, name: str) -> BrandPreset:
        try:
            return self.presets[name]
        except KeyError:
            available = ", ".join(sorted(self.presets))
            raise KeyError(f"Unknown style preset '{name}'. Available: {available}") from None


@lru_cache(maxsize=1)
def get_settings() -> AuraGenSettings:
    return AuraGenSettings()


@lru_cache(maxsize=4)
def load_brand_book(path: Path | None = None) -> BrandBook:
    brand_path = path or get_settings().brand_file
    data = json.loads(Path(brand_path).read_text(encoding="utf-8"))
    return BrandBook.model_validate(data)
