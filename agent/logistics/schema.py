"""Approved, versioned schemas for deterministic logistics validation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


SchemaDataType = Literal["text", "integer", "decimal", "date", "boolean"]
FieldPriority = Literal["required", "recommended", "optional"]


class SchemaField(BaseModel):
    field_name: str
    semantic_role: str
    field_priority: FieldPriority = "optional"
    data_type: SchemaDataType = "text"
    pattern: Optional[str] = None
    min_length: Optional[int] = Field(default=None, ge=0)
    max_length: Optional[int] = Field(default=None, ge=0)
    dictionary_reference: Optional[str] = None
    sequence_rule: Optional[str] = None


class ApprovedSchema(BaseModel):
    """A schema that may be used for validation only after approval."""

    schema_name: str
    schema_version: str
    fields: list[SchemaField]
    approved_by_user: Optional[str] = None
    approved_at: Optional[datetime] = None

    @property
    def is_approved(self) -> bool:
        return bool(self.approved_by_user and self.approved_at)

    def approve(self, user: str) -> "ApprovedSchema":
        user = user.strip()
        if not user:
            raise ValueError("Approval user cannot be blank")
        self.approved_by_user = user
        self.approved_at = datetime.now(timezone.utc)
        return self

    def field(self, field_name: str) -> SchemaField:
        for item in self.fields:
            if item.field_name == field_name:
                return item
        raise KeyError(f"Unknown schema field: {field_name}")
