"""Field-level validation and review audit contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


ValidationStatus = Literal["PASS", "WARNING", "REVIEW", "ERROR"]
ReviewPriority = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
ReviewDecision = Literal["APPROVED", "REJECTED", "CORRECTED"]


class ValidationFinding(BaseModel):
    code: str
    points: int = Field(ge=0)
    reason: str


class FieldAudit(BaseModel):
    record_id: str
    field_name: str
    original_ocr_value: Optional[str] = None
    suggested_value: Optional[str] = None
    final_value: Optional[str] = None
    validation_status: ValidationStatus = "ERROR"
    ocr_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    pattern_match_score: int = Field(default=0, ge=0, le=100)
    confidence_score: int = Field(default=0, ge=0, le=100)
    review_priority: ReviewPriority = "CRITICAL"
    deduction_codes: list[str] = Field(default_factory=list)
    deduction_total: int = Field(default=0, ge=0)
    validation_rules: list[str] = Field(default_factory=list)
    findings: list[ValidationFinding] = Field(default_factory=list)
    source_document: Optional[str] = None
    source_page: Optional[int] = Field(default=None, ge=1)
    source_region: Optional[str] = None
    potential_calculated_field: bool = False
    calculation_reason: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_comment: Optional[str] = None


class ReviewEvent(BaseModel):
    record_id: str
    field_name: str
    decision: ReviewDecision
    original_ocr_value: Optional[str] = None
    suggested_value: Optional[str] = None
    final_value: Optional[str] = None
    reviewed_by: str
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    review_comment: Optional[str] = None
