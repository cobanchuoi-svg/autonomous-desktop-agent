"""Durable job progress and recovery events."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class JobProgress(BaseModel):
    job_id: str
    schema_version: str
    source_document: Optional[str] = None
    current_scroll_iteration: int = Field(default=0, ge=0)
    rows_processed: int = Field(default=0, ge=0)
    processed_record_ids: list[str] = Field(default_factory=list)
    last_overlap_rows: list[str] = Field(default_factory=list)
    last_success_time: Optional[datetime] = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def mark_batch_success(
        self,
        rows_processed: int,
        record_ids: list[str],
        overlap_rows: list[str],
        scroll_iteration: Optional[int] = None,
    ) -> None:
        if rows_processed < 0:
            raise ValueError("rows_processed cannot be negative")
        self.rows_processed += rows_processed
        self.processed_record_ids = list(dict.fromkeys(self.processed_record_ids + record_ids))
        self.last_overlap_rows = list(overlap_rows)
        if scroll_iteration is not None:
            self.current_scroll_iteration = scroll_iteration
        now = datetime.now(timezone.utc)
        self.last_success_time = now
        self.updated_at = now


class RecoveryEvent(BaseModel):
    job_id: str
    recovery_reason: str
    recovered_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    resumed_from_scroll_iteration: int = 0
    resumed_from_rows_processed: int = 0
    note: Optional[str] = None


class ProgressStore:
    """Atomic JSON progress store; recovery events are append-only."""

    def __init__(self, progress_path: Path, events_path: Optional[Path] = None):
        self.progress_path = Path(progress_path)
        self.events_path = events_path or self.progress_path.with_name("recovery_events.jsonl")

    def save(self, progress: JobProgress) -> None:
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.progress_path.with_suffix(self.progress_path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(progress.model_dump(mode="json"), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(self.progress_path)

    def load(self) -> Optional[JobProgress]:
        if not self.progress_path.exists():
            return None
        return JobProgress.model_validate_json(self.progress_path.read_text(encoding="utf-8"))

    def append_recovery_event(self, event: RecoveryEvent) -> None:
        self.events_path.parent.mkdir(parents=True, exist_ok=True)
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json"), ensure_ascii=False) + "\n")
