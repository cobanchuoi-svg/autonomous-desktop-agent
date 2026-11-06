"""Stable internal data contracts for logistics-document workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


FieldSource = Literal["ocr", "pdf_text", "excel", "llm", "user_correction"]


class ExtractionField(BaseModel):
    """A value plus the evidence and provenance needed to audit it."""

    original: Optional[str] = None
    final: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_text: Optional[str] = None
    source: FieldSource = "ocr"
    corrected_at: Optional[datetime] = None

    @property
    def value(self) -> Optional[str]:
        return self.final if self.final is not None else self.original


class LineItem(BaseModel):
    description: ExtractionField = Field(default_factory=ExtractionField)
    quantity: ExtractionField = Field(default_factory=ExtractionField)
    unit_price: ExtractionField = Field(default_factory=ExtractionField)
    amount: ExtractionField = Field(default_factory=ExtractionField)


class DocumentRecord(BaseModel):
    """Normalized record used before adapting data to a customer import format."""

    document_id: str
    document_type: Optional[str] = None
    bill_of_lading_no: ExtractionField = Field(default_factory=ExtractionField)
    shipper: ExtractionField = Field(default_factory=ExtractionField)
    consignee: ExtractionField = Field(default_factory=ExtractionField)
    vessel: ExtractionField = Field(default_factory=ExtractionField)
    port_of_loading: ExtractionField = Field(default_factory=ExtractionField)
    port_of_discharge: ExtractionField = Field(default_factory=ExtractionField)
    invoice_no: ExtractionField = Field(default_factory=ExtractionField)
    invoice_date: ExtractionField = Field(default_factory=ExtractionField)
    currency: ExtractionField = Field(default_factory=ExtractionField)
    total_amount: ExtractionField = Field(default_factory=ExtractionField)
    line_items: list[LineItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def get_value(self, field_name: str) -> Optional[str]:
        field = getattr(self, field_name, None)
        if not isinstance(field, ExtractionField):
            raise KeyError(f"Unknown extractable field: {field_name}")
        return field.value


class FieldMapping(BaseModel):
    target_column: str
    source_field: str
    required: bool = False
    date_format: Optional[str] = None
    decimal_places: Optional[int] = Field(default=None, ge=0, le=6)


class ImportTemplate(BaseModel):
    """Approved target-system mapping; one template can belong to one customer."""

    target_system: str
    format: Literal["csv"] = "csv"
    mappings: list[FieldMapping]
    delimiter: str = ","
    encoding: str = "utf-8-sig"

    @field_validator("delimiter")
    @classmethod
    def one_character_delimiter(cls, value: str) -> str:
        if len(value) != 1:
            raise ValueError("delimiter must be exactly one character")
        return value


def normalize_decimal(value: Optional[str], decimal_places: Optional[int] = None) -> Optional[str]:
    """Return a canonical decimal string without silently guessing locale."""
    if value is None or not str(value).strip():
        return None
    candidate = str(value).strip().replace(" ", "").replace(",", "")
    try:
        number = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc
    if decimal_places is not None:
        number = number.quantize(Decimal(1).scaleb(-decimal_places))
        return f"{number:.{decimal_places}f}"
    return format(number, "f")
