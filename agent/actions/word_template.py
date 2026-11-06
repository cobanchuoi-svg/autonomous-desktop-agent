"""Fill {{PLACEHOLDER}} variables in a Word (.docx) template.

Uses python-docx; falls back gracefully if the package is unavailable.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List


_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


def list_placeholders(template_path: str) -> List[str]:
    """Scan a .docx template and return all unique {{PLACEHOLDER}} names found.

    Returns an empty list if the file cannot be opened or python-docx is missing.
    """
    try:
        from docx import Document
    except ImportError:
        return []

    path = Path(template_path)
    if not path.is_file():
        return []

    try:
        doc = Document(str(path))
    except Exception:
        return []

    found: set = set()
    for para in doc.paragraphs:
        for m in _PLACEHOLDER_RE.finditer(para.text):
            found.add(m.group(1))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for m in _PLACEHOLDER_RE.finditer(para.text):
                        found.add(m.group(1))
    return sorted(found)


def _replace_in_paragraph(para: Any, fields: Dict[str, str]) -> int:
    """Replace {{PLACEHOLDER}} inside a paragraph, preserving run-level formatting."""
    full_text = "".join(run.text for run in para.runs)
    replaced_text = full_text
    replaced_keys: set = set()
    for key, val in fields.items():
        marker = "{{" + key + "}}"
        if marker in replaced_text:
            replaced_text = replaced_text.replace(marker, val)
            replaced_keys.add(key)

    if replaced_text == full_text:
        return 0

    if para.runs:
        para.runs[0].text = replaced_text
        for run in para.runs[1:]:
            run.text = ""
    return len(replaced_keys)


def fill_word_template(
    template_path: str,
    output_path: str,
    fields: Dict[str, str],
) -> Dict[str, Any]:
    """Fill {{FIELD_NAME}} placeholders in a Word template and save to output_path.

    Args:
        template_path: Path to the .docx template file.
        output_path:   Where to save the filled document.
        fields:        Dict mapping FIELD_NAME -> replacement value.

    Returns:
        {"success": bool, "path": str, "replaced": int,
         "not_found": list[str], "message": str}
    """
    try:
        from docx import Document
    except ImportError:
        return {
            "success": False, "path": output_path, "replaced": 0,
            "not_found": list(fields.keys()),
            "message": "python-docx not installed. Run: pip install python-docx",
        }

    src = Path(template_path)
    if not src.is_file():
        return {
            "success": False, "path": output_path, "replaced": 0,
            "not_found": list(fields.keys()),
            "message": f"Template not found: {template_path}",
        }

    try:
        doc = Document(str(src))
    except Exception as exc:
        return {
            "success": False, "path": output_path, "replaced": 0,
            "not_found": list(fields.keys()),
            "message": f"Cannot open template: {exc}",
        }

    total_replaced = 0
    used_keys: set = set()

    for para in doc.paragraphs:
        for key in fields:
            if "{{" + key + "}}" in para.text:
                used_keys.add(key)
        total_replaced += _replace_in_paragraph(para, fields)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for para in cell.paragraphs:
                    for key in fields:
                        if "{{" + key + "}}" in para.text:
                            used_keys.add(key)
                    total_replaced += _replace_in_paragraph(para, fields)

    not_found = [k for k in fields if k not in used_keys]

    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        doc.save(str(out))
    except Exception as exc:
        return {
            "success": False, "path": str(out), "replaced": total_replaced,
            "not_found": not_found, "message": f"Cannot save output: {exc}",
        }

    return {
        "success": True,
        "path": str(out),
        "replaced": total_replaced,
        "not_found": not_found,
        "message": (
            f"Da dien {total_replaced} placeholder vao {out.name}."
            + (f" Khong tim thay: {not_found}" if not_found else "")
        ),
    }
