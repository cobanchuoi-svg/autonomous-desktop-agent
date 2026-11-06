"""Generate Excel (.xlsx) files from OCR results or extracted field pairs.

Uses openpyxl; falls back gracefully if the package is unavailable.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List


def _auto_width(ws, max_chars: int = 50) -> None:
    """Approximate column widths from cell content."""
    for col in ws.columns:
        length = max(
            min(len(str(cell.value or "")), max_chars) for cell in col
        )
        ws.column_dimensions[col[0].column_letter].width = max(length + 2, 10)


def _looks_like_header(row: List[str]) -> bool:
    """Heuristic: treat row as header if most cells are ALL_UPPER or end with ':'."""
    if not row:
        return False
    hits = sum(1 for c in row if c.isupper() or c.endswith(":") or c.endswith("："))
    return hits >= len(row) // 2


def generate_excel_from_ocr(
    ocr_result: Dict[str, Any],
    output_path: str,
    sheet_name: str = "OCR Data",
) -> Dict[str, Any]:
    """Generate an Excel file from an OCR result dict.

    ocr_result keys:
        ``full_text`` (str): raw OCR text, tab/multi-space delimited.
        ``rows`` (list[list]): pre-parsed 2-D table (optional, preferred).

    Returns {"success": bool, "path": str, "rows_written": int, "message": str}.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return {"success": False, "path": output_path, "rows_written": 0,
                "message": "openpyxl is not installed. Run: pip install openpyxl"}

    if "rows" in ocr_result and ocr_result["rows"]:
        table: List[List[str]] = [[str(c) for c in r] for r in ocr_result["rows"]]
    else:
        raw = str(ocr_result.get("full_text", "")).strip()
        if not raw:
            return {"success": False, "path": output_path, "rows_written": 0,
                    "message": "OCR result is empty."}
        table = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            if "\t" in line:
                cols = [c.strip() for c in line.split("\t")]
            else:
                cols = [c.strip() for c in re.split(r" {2,}", line.strip())]
            cols = [c for c in cols if c]
            if cols:
                table.append(cols)

    if not table:
        return {"success": False, "path": output_path, "rows_written": 0,
                "message": "No data rows found in OCR result."}

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    header_fill = PatternFill("solid", fgColor="4F81BD")
    header_font = Font(bold=True, color="FFFFFF")
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    is_first = True
    rows_written = 0
    for row_data in table:
        ws.append(row_data)
        if is_first and _looks_like_header(row_data):
            for cell in ws[ws.max_row]:
                cell.font = header_font
                cell.fill = header_fill
                cell.alignment = center
        is_first = False
        rows_written += 1

    _auto_width(ws)
    ws.freeze_panes = "A2"
    wb.save(str(target))
    return {
        "success": True,
        "path": str(target),
        "rows_written": rows_written,
        "message": f"Da xuat {rows_written} dong vao {target.name}",
    }


def generate_excel_from_fields(
    fields: List[Dict[str, str]],
    output_path: str,
    sheet_name: str = "Fields",
) -> Dict[str, Any]:
    """Write a list of key-value pairs as a 2-column Excel table (Key | Value).

    Returns {"success": bool, "path": str, "rows_written": int, "message": str}.
    """
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return {"success": False, "path": output_path, "rows_written": 0,
                "message": "openpyxl is not installed."}

    if not fields:
        return {"success": False, "path": output_path, "rows_written": 0,
                "message": "No fields to write."}

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name[:31]

    header_fill = PatternFill("solid", fgColor="4F81BD")
    header_font = Font(bold=True, color="FFFFFF")

    ws.append(["Truong", "Gia tri"])
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill

    rows_written = 0
    for pair in fields:
        ws.append([pair.get("key", ""), pair.get("normalized", pair.get("value", ""))])
        rows_written += 1

    _auto_width(ws)
    ws.freeze_panes = "A2"
    wb.save(str(target))
    return {
        "success": True,
        "path": str(target),
        "rows_written": rows_written,
        "message": f"Da xuat {rows_written} truong vao {target.name}",
    }

def generate_csv_from_ocr(
    ocr_result: Dict[str, Any],
    output_path: str,
) -> Dict[str, Any]:
    """Generate a clean CSV file from an OCR result dict with utf-8-sig encoding.
    
    Compatible with Excel, WPS, Google Sheets and all data tools.
    """
    import csv

    if "rows" in ocr_result and ocr_result["rows"]:
        table = [[str(c) for c in r] for r in ocr_result["rows"]]
    else:
        raw = str(ocr_result.get("full_text", "")).strip()
        if not raw:
            return {"success": False, "path": output_path, "rows_written": 0, "message": "OCR result is empty."}
        table = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            if "\t" in line:
                cols = [c.strip() for c in line.split("\t")]
            else:
                cols = [c.strip() for c in re.split(r" {2,}", line.strip())]
            cols = [c for c in cols if c]
            if cols:
                table.append(cols)

    if not table:
        return {"success": False, "path": output_path, "rows_written": 0, "message": "No data rows found in OCR result."}

    target = Path(output_path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerows(table)

    return {
        "success": True,
        "path": str(target),
        "rows_written": len(table),
        "message": f"Da xuat {len(table)} dong vao {target.name}",
    }

