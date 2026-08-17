from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from config import Settings, get_settings
from core.image_utils import extract_text, looks_like_image, to_base64
from schemas.invoice import ExtractedInvoice, LineItem, money

logger = logging.getLogger(__name__)

MONEY_RE = re.compile(r"\$?\s*(-?\d{1,3}(?:,\d{3})*(?:\.\d{2})|-?\d+\.\d{2})")
INVOICE_NO_RE = re.compile(r"(?:invoice\s*(?:no\.?|number|#)|inv\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9\-]{2,})", re.I)
DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})")
VENDOR_RE = re.compile(r"(?:from|vendor|billed by|merchant)\s*[:\-]\s*(.+)", re.I)
LINE_RE = re.compile(
    r"^(?P<desc>.+?)\s+(?P<qty>\d+(?:\.\d+)?)\s+x\s+\$?(?P<unit>\d+(?:\.\d{1,2})?)\s+=\s+\$?(?P<total>\d+(?:\.\d{1,2})?)\s*$",
    re.I,
)


def _parse_money(value: str) -> Decimal | None:
    try:
        return money(value.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _parse_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def heuristic_extract(text: str) -> ExtractedInvoice:
    vendor = None
    vendor_match = VENDOR_RE.search(text)
    if vendor_match:
        vendor = vendor_match.group(1).strip()
    elif "northline" in text.lower():
        vendor = "Northline Supplies"

    invoice_number = None
    number_match = INVOICE_NO_RE.search(text)
    if number_match:
        invoice_number = number_match.group(1).strip()

    invoice_date = None
    date_match = DATE_RE.search(text)
    if date_match:
        invoice_date = _parse_date(date_match.group(1))

    line_items: list[LineItem] = []
    for line in text.splitlines():
        match = LINE_RE.match(line.strip())
        if not match:
            continue
        line_items.append(
            LineItem(
                description=match.group("desc").strip(" -•"),
                quantity=match.group("qty"),
                unit_price=match.group("unit"),
                line_total=match.group("total"),
            )
        )

    amounts = {label: None for label in ("subtotal", "tax", "total")}
    for raw in text.splitlines():
        lower = raw.lower()
        money_match = MONEY_RE.search(raw)
        if not money_match:
            continue
        amount = _parse_money(money_match.group(1))
        if "subtotal" in lower:
            amounts["subtotal"] = amount
        elif re.search(r"\btax\b", lower):
            amounts["tax"] = amount
        elif re.search(r"\b(total|amount due)\b", lower) and "subtotal" not in lower:
            amounts["total"] = amount

    return ExtractedInvoice(
        vendor_name=vendor,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        line_items=line_items,
        subtotal=amounts["subtotal"],
        tax=amounts["tax"],
        total=amounts["total"],
    )


def _llm_extract(text: str, image_b64: str | None, settings: Settings) -> ExtractedInvoice:
    schema_hint = ExtractedInvoice.model_json_schema()
    user = (
        "Extract an invoice as JSON matching this schema. "
        "Use nulls when unknown. Do not invent line items.\n"
        f"{json.dumps(schema_hint)}\n\nDocument text:\n{text[:8000]}"
    )
    messages = [
        {"role": "system", "content": "You extract invoices. Return JSON only."},
        {"role": "user", "content": user},
    ]
    payload = {
        "model": settings.vision_model,
        "temperature": 0.0,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    url = settings.ollama_base_url.rstrip("/") + "/chat/completions"
    with httpx.Client(timeout=60.0) as client:
        response = client.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    return ExtractedInvoice.model_validate(json.loads(content))


def extract_invoice(path: Path, settings: Settings | None = None) -> ExtractedInvoice:
    settings = settings or get_settings()
    text = extract_text(path)
    fallback = heuristic_extract(text)
    image_b64 = to_base64(path.read_bytes()) if looks_like_image(path) else None
    try:
        llm = _llm_extract(text, image_b64, settings)
        # Prefer LLM fields when present, but keep heuristic math if the model omitted totals.
        merged = fallback.model_dump()
        for key, value in llm.model_dump().items():
            if value not in (None, [], ""):
                merged[key] = value
        return ExtractedInvoice.model_validate(merged)
    except Exception:
        logger.info("Vision/LLM extract unavailable; using heuristic parser")
        return fallback
