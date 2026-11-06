"""Bounded rolling memory for table patches and overlap-based deduplication."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from agent.logistics.patch_context import GroupContext, PatchContext, PatchRow


class RollingPatchState(BaseModel):
    current_patch_id: Optional[str] = None
    retained_overlap: list[PatchRow] = Field(default_factory=list)
    current_group_context: Optional[GroupContext] = None
    processed_row_keys: set[str] = Field(default_factory=set)


class RollingPatchMemory:
    """Keep only the active patch and a bounded overlap window."""

    def __init__(self, overlap_size: int = 5):
        if overlap_size < 1:
            raise ValueError("overlap_size must be positive")
        self.overlap_size = overlap_size
        self.state = RollingPatchState()

    def prepare(self, patch: PatchContext) -> list[PatchRow]:
        """Return rows not already committed, preserving patch order."""
        if self.state.current_group_context is None and patch.group_context:
            self.state.current_group_context = patch.group_context
        return [
            row for row in patch.rows
            if row.row_key not in self.state.processed_row_keys
        ]

    def commit(self, patch: PatchContext, rows: list[PatchRow]) -> None:
        """Commit a verified batch and retain only the overlap tail."""
        if patch.completeness_status != "COMPLETE":
            raise ValueError("Cannot commit an incomplete or drifted patch")
        self.state.current_patch_id = patch.patch_id
        self.state.processed_row_keys.update(row.row_key for row in rows)
        if patch.group_context:
            self.state.current_group_context = patch.group_context
        self.state.retained_overlap = list(patch.rows[-self.overlap_size:])

    def merge_with_overlap(self, patch: PatchContext) -> list[PatchRow]:
        """Return overlap plus new rows, deduplicated by stable row key."""
        merged: list[PatchRow] = []
        seen: set[str] = set()
        for row in [*self.state.retained_overlap, *patch.rows]:
            if row.row_key not in seen:
                merged.append(row)
                seen.add(row.row_key)
        return merged

    def clear_transient_patch(self) -> None:
        """Drop active patch data while keeping recognition state and overlap."""
        self.state.current_patch_id = None
