"""Organized outputs + reproducibility metadata.

Every run gets its own dated folder:

    outputs/2026-07-19/143212_misty-mountain-temple/
        ├── metadata.json      (prompt, model, seed, params, timings)
        └── *.png / *.mp4

and is appended to ``outputs/history.jsonl`` which powers
``auragen history`` / ``auragen gallery``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from auragen.utils.image_utils import slugify

HISTORY_FILENAME = "history.jsonl"


class RunRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    command: str
    task: str
    prompt: str
    negative_prompt: str = ""
    style: str | None = None
    provider: str = ""
    model_id: str = ""
    seed: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None


class HistoryStore:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root
        self.history_path = output_root / HISTORY_FILENAME

    def new_run_dir(self, prompt: str) -> Path:
        now = datetime.now()
        run_dir = self.output_root / now.strftime("%Y-%m-%d") / f"{now.strftime('%H%M%S')}_{slugify(prompt)}"
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def save(self, record: RunRecord, run_dir: Path) -> None:
        (run_dir / "metadata.json").write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )
        self.output_root.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json() + "\n")

    def load(self, limit: int | None = None, task: str | None = None) -> list[RunRecord]:
        if not self.history_path.exists():
            return []
        records: list[RunRecord] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = RunRecord.model_validate(json.loads(line))
            except Exception:
                continue  # tolerate hand-edited/corrupt lines
            if task and record.task != task:
                continue
            records.append(record)
        records.sort(key=lambda item: item.created_at, reverse=True)
        return records[:limit] if limit else records
