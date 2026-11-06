"""Business-layer field extraction and normalization from OCR text.

No LLM calls — pure local heuristics only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional


# ─────────────────────────── Date normalization ───────────────────────────────

_DATE_PATTERNS = [
    (r"(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})", "dmy"),
    (r"(\d{4})[/\-\.](\d{1,2})[/\-\.](\d{1,2})", "ymd"),
    (r"ng[àa]y\s+(\d{1,2})\s+th[áa]ng\s+(\d{1,2})\s+n[ăa]m\s+(\d{4})", "dmy_vn"),
    (r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})$", "dmy_short"),
]


def normalize_date(text: str) -> str:
    """Parse a Vietnamese or English date string to ISO YYYY-MM-DD.

    Returns the ISO string on success, or the original text unchanged.
    """
    t = text.strip()
    for pattern, fmt in _DATE_PATTERNS:
        m = re.search(pattern, t, re.IGNORECASE)
        if not m:
            continue
        g = m.groups()
        try:
            if fmt in ("dmy", "dmy_vn"):
                d, mo, y = int(g[0]), int(g[1]), int(g[2])
            elif fmt == "ymd":
                y, mo, d = int(g[0]), int(g[1]), int(g[2])
            elif fmt == "dmy_short":
                d, mo, y = int(g[0]), int(g[1]), 2000 + int(g[2])
            else:
                continue
            if 1 <= mo <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
                return f"{y:04d}-{mo:02d}-{d:02d}"
        except (ValueError, IndexError):
            continue
    return text


# ─────────────────────────── Number normalization ─────────────────────────────

def normalize_number(text: str) -> "float | str":
    """Parse a Vietnamese/European number string (1.000,50 -> 1000.50).

    Returns float on success, original text unchanged on failure.
    """
    t = text.strip()
    t = re.sub(r"[^\d.,]", "", t)
    if re.match(r"^\d{1,3}(\.\d{3})+(,\d+)?$", t):
        t = t.replace(".", "").replace(",", ".")
    elif re.match(r"^\d{1,3}(,\d{3})+(\.\d+)?$", t):
        t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return text


# ─────────────────────────── Currency normalization ───────────────────────────

_CURRENCY_MAP = {
    "vnd": "VND", "vnđ": "VND", "đ": "VND", "dong": "VND",
    "usd": "USD", "$": "USD", "dollar": "USD",
    "eur": "EUR", "gbp": "GBP",
}


def normalize_currency(text: str) -> Dict[str, Any]:
    """Detect currency and amount from a string like '1.500.000đ' or '$29.99'.

    Returns {"amount": float | None, "currency": str | None, "raw": str}.
    """
    t = text.strip()
    currency = None
    for sym, code in _CURRENCY_MAP.items():
        if sym.lower() in t.lower():
            currency = code
            break
    amount_str = re.sub(r"[a-zA-ZđĐ$€£\s]", "", t)
    num = normalize_number(amount_str)
    return {
        "amount": num if isinstance(num, float) else None,
        "currency": currency,
        "raw": text,
    }


# ─────────────────────────── Key-value extraction ────────────────────────────

_KV_SPLITTER = re.compile(r"\s*[:：]\s*|\t+")


def extract_key_value_pairs(ocr_text: str) -> List[Dict[str, str]]:
    """Scan OCR text for KEY: value or KEY\\tvalue patterns.

    Returns list of dicts with keys: 'key', 'value', 'normalized'.
    """
    results: List[Dict[str, str]] = []
    for line in ocr_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = _KV_SPLITTER.split(line, maxsplit=1)
        if len(parts) == 2:
            key, val = parts[0].strip(), parts[1].strip()
            if not key or not val or len(key) > 80:
                continue
            norm = val
            if re.search(r"\d", val):
                date_try = normalize_date(val)
                if date_try != val:
                    norm = date_try
                else:
                    num_try = normalize_number(val)
                    norm = str(num_try) if isinstance(num_try, float) else val
            results.append({"key": key, "value": val, "normalized": norm})
    return results


# ─────────────────────────── Table row extraction ────────────────────────────

def extract_table_rows(ocr_text: str) -> List[List[str]]:
    """Detect tab-separated or multi-space-separated columns from OCR text.

    Returns a 2-D list (rows x cols). Skips blank lines.
    """
    rows: List[List[str]] = []
    for line in ocr_text.splitlines():
        if not line.strip():
            continue
        if "\t" in line:
            cols = [c.strip() for c in line.split("\t")]
        else:
            cols = [c.strip() for c in re.split(r" {2,}", line.strip())]
        cols = [c for c in cols if c]
        if cols:
            rows.append(cols)
    return rows


# ─────────────────────────── Schema validation ───────────────────────────────

@dataclass
class FieldSchema:
    """Expected type and constraints for a single extracted field."""

    name: str
    type: Literal["date", "number", "currency", "text"] = "text"
    required: bool = False
    pattern: Optional[str] = None


def validate_fields(
    extracted_pairs: List[Dict[str, str]],
    schema: List[FieldSchema],
) -> Dict[str, Any]:
    """Validate extracted key-value pairs against a list of FieldSchema rules.

    Returns {"valid": bool, "errors": list[str], "warnings": list[str]}.
    """
    errors: List[str] = []
    warnings: List[str] = []
    found = {p["key"].lower(): p for p in extracted_pairs}

    for fld in schema:
        pair = found.get(fld.name.lower())
        if pair is None:
            (errors if fld.required else warnings).append(
                f"{'Required' if fld.required else 'Optional'} field '{fld.name}' not found."
            )
            continue
        val = pair["normalized"]
        if fld.type == "date" and not re.match(r"\d{4}-\d{2}-\d{2}", val):
            errors.append(f"Field '{fld.name}': expected date, got '{val}'")
        elif fld.type in ("number", "currency"):
            try:
                float(val.replace(",", "."))
            except ValueError:
                errors.append(f"Field '{fld.name}': expected number, got '{val}'")
        if fld.pattern and not re.search(fld.pattern, val, re.IGNORECASE):
            errors.append(f"Field '{fld.name}': '{val}' does not match pattern '{fld.pattern}'")

    return {"valid": not errors, "errors": errors, "warnings": warnings}
