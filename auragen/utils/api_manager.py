"""Multi-provider execution with retries and graceful fallback.

Order of preference comes from settings (``AURAGEN_ENGINE_ORDER``), or a
single engine can be pinned with ``--engine`` / ``AURAGEN_ENGINE``. For a
given task the manager walks the chain: unconfigured engines and engines
that don't support the task are skipped; rate limits are retried with
exponential backoff, then we fall through to the next provider. Only when
every provider has failed does the user see an error — with the full
per-provider breakdown.
"""

from __future__ import annotations

import time

from rich.console import Console

from auragen.config.settings import AuraGenSettings, EngineName
from auragen.engines.base import (
    BaseEngine,
    EngineError,
    EngineNotConfigured,
    GenerationRequest,
    GenerationResult,
    RateLimitError,
    Task,
    TaskNotSupported,
)
from auragen.engines.comfy_engine import ComfyUIEngine
from auragen.engines.fal_engine import FalEngine
from auragen.engines.hf_engine import HuggingFaceEngine
from auragen.engines.replicate_engine import ReplicateEngine

ENGINE_REGISTRY: dict[EngineName, type[BaseEngine]] = {
    EngineName.FAL: FalEngine,
    EngineName.REPLICATE: ReplicateEngine,
    EngineName.HUGGINGFACE: HuggingFaceEngine,
    EngineName.COMFYUI: ComfyUIEngine,
}


class AllEnginesFailed(EngineError):
    """Every engine in the chain failed or was unavailable."""

    def __init__(self, task: Task, failures: dict[str, str]) -> None:
        self.failures = failures
        detail = "; ".join(f"{name}: {reason}" for name, reason in failures.items()) or "no engines in chain"
        super().__init__(f"All engines failed for {task.value} — {detail}")


class APIManager:
    def __init__(
        self,
        settings: AuraGenSettings,
        console: Console | None = None,
        engine_override: EngineName | None = None,
    ) -> None:
        self.settings = settings
        self.console = console or Console()
        pinned = engine_override or settings.engine
        order = [pinned] if pinned else settings.engine_order
        self.engines: list[BaseEngine] = [ENGINE_REGISTRY[name](settings) for name in order]

    def engine_status(self) -> dict[str, bool]:
        """Provider name -> configured? (used by `auragen doctor`)."""
        return {engine.name: engine.is_configured() for engine in self.engines}

    def execute(self, task: Task, request: GenerationRequest) -> GenerationResult:
        failures: dict[str, str] = {}

        for engine in self.engines:
            if not engine.supports(task):
                failures[engine.name] = f"does not support {task.value}"
                continue
            if not engine.is_configured():
                failures[engine.name] = "not configured (missing key/SDK or server offline)"
                continue

            attempts = 1 + self.settings.max_retries_per_engine
            for attempt in range(1, attempts + 1):
                try:
                    self.console.log(
                        f"[cyan]{engine.name}[/cyan] → {task.value}"
                        + (f" (attempt {attempt}/{attempts})" if attempt > 1 else "")
                    )
                    return engine.run(task, request)
                except RateLimitError as exc:
                    if attempt < attempts:
                        delay = self.settings.retry_backoff_seconds * (2 ** (attempt - 1))
                        self.console.log(f"[yellow]{engine.name} rate limited; retrying in {delay:.0f}s[/yellow]")
                        time.sleep(delay)
                        continue
                    failures[engine.name] = f"rate limited after {attempts} attempts"
                    self.console.log(f"[yellow]{engine.name} exhausted; falling back[/yellow]")
                    break
                except (EngineNotConfigured, TaskNotSupported) as exc:
                    failures[engine.name] = str(exc)
                    break
                except EngineError as exc:
                    failures[engine.name] = str(exc)
                    self.console.log(f"[red]{engine.name} failed:[/red] {exc} — falling back")
                    break

        raise AllEnginesFailed(task, failures)
