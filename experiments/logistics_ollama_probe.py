"""Standalone prompt experiment: OCR text -> local Ollama -> logistics JSON.

It does not start the agent, FSM, screenshot capture, or desktop actions.

Example:
    python experiments/logistics_ollama_probe.py --text "Invoice No: INV-001 Total USD 1250"
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


FIELDS = (
    "bill_of_lading_no", "shipper", "consignee", "vessel", "port_of_loading",
    "port_of_discharge", "invoice_no", "invoice_date", "currency", "total_amount",
)

FIELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "value": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence_text": {"type": ["string", "null"]},
    },
    "required": ["value", "confidence", "evidence_text"],
    "additionalProperties": False,
}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "document_type": {"type": ["string", "null"]},
        "fields": {
            "type": "object",
            "properties": {name: FIELD_SCHEMA for name in FIELDS},
            "required": list(FIELDS),
            "additionalProperties": False,
        },
    },
    "required": ["document_type", "fields"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You extract structured facts from logistics document OCR. "
    "Use only text explicitly present in the OCR input. Never infer, repair, "
    "or invent missing values. For each field return the exact supporting OCR "
    "fragment as evidence_text. If absent, return value=null, confidence=0.0, "
    "and evidence_text=null. Return JSON matching the supplied schema only."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract logistics fields with local Ollama.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="OCR text to analyse.")
    source.add_argument("--file", help="UTF-8 file containing OCR text.")
    source.add_argument("--stdin", action="store_true", help="Read OCR text from stdin.")
    parser.add_argument("--model", default="qwen2.5:3b", help="Installed Ollama model.")
    parser.add_argument("--url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args()


def load_text(args: argparse.Namespace) -> str:
    if args.text is not None:
        return args.text.strip()
    if args.file:
        with open(args.file, "r", encoding="utf-8") as source:
            return source.read().strip()
    return sys.stdin.read().strip()


def call_ollama(url: str, model: str, text: str, timeout: float) -> dict[str, Any]:
    payload = {
        "model": model,
        "stream": False,
        "format": SCHEMA,
        "options": {"temperature": 0},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"OCR text:\n---\n{text}\n---"},
        ],
    }
    request = Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            envelope = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"Ollama returned HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:500]}") from exc
    except URLError as exc:
        raise RuntimeError("Could not reach Ollama. Start it with: ollama serve") from exc

    content = str(envelope.get("message", {}).get("content", "")).strip()
    if not content:
        raise RuntimeError("Ollama returned no message content.")
    try:
        result = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Model did not return valid JSON: {content[:500]}") from exc
    if not isinstance(result, dict):
        raise RuntimeError("Model JSON output must be an object.")
    return result


def main() -> int:
    args = parse_args()
    text = load_text(args)
    if not text:
        print("No OCR text was supplied.", file=sys.stderr)
        return 2
    try:
        result = call_ollama(args.url, args.model, text, args.timeout)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
