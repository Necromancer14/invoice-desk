"""The fields the desk extracts from an invoice, in one place."""
from __future__ import annotations

import math

SCALARS = ["invoice_number", "issue_date", "due_date", "seller_name", "seller_vat", "buyer_name",
           "buyer_vat", "currency", "subtotal", "vat_amount", "total", "qr_payload"]
NUMERIC = {"subtotal", "vat_amount", "total"}
# invoice_type ("standard" or "simplified") is read but not scored by the evaluation, so its figures stay comparable
FIELDS = SCALARS + ["invoice_type", "line_items"]
# What a reviewer must be able to rely on before an invoice is auto-approved.
REQUIRED = ["invoice_number", "issue_date", "seller_name", "seller_vat", "currency",
            "subtotal", "vat_amount", "total"]

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_number": {"type": ["string", "null"]},
        "issue_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "due_date": {"type": ["string", "null"], "description": "ISO date YYYY-MM-DD"},
        "seller_name": {"type": ["string", "null"], "description": "As printed, in its original language"},
        "seller_vat": {"type": ["string", "null"], "description": "Seller VAT registration number, digits only"},
        "buyer_name": {"type": ["string", "null"]},
        "buyer_vat": {"type": ["string", "null"]},
        "currency": {"type": ["string", "null"], "description": "ISO code such as SAR"},
        "subtotal": {"type": ["number", "null"], "description": "Total excluding VAT"},
        "vat_amount": {"type": ["number", "null"]},
        "total": {"type": ["number", "null"], "description": "Total including VAT"},
        "qr_payload": {"type": ["string", "null"], "description": "Base64 text printed next to the QR code, if any"},
        "invoice_type": {"type": ["string", "null"], "description": "standard (tax invoice) or simplified (simplified tax invoice); null if not stated"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "line_total": {"type": ["number", "null"]},
                    "vat_category": {"type": ["string", "null"],
                                     "description": "S standard rate, Z zero-rated, E exempt, O out of scope. Null if not shown."},
                },
                "required": ["description"],
            },
        },
        "field_confidence": {
            "type": "object",
            "description": "Confidence from 0 to 1 for each field above",
            "additionalProperties": {"type": "number"},
        },
        "notes": {"type": "array", "items": {"type": "string"}, "description": "Anything ambiguous or unreadable"},
    },
    "required": ["invoice_number", "issue_date", "seller_name", "seller_vat", "currency",
                 "subtotal", "vat_amount", "total", "line_items", "field_confidence"],
}


def empty_fields() -> dict:
    d = {k: None for k in SCALARS}
    d["invoice_type"] = None
    d["line_items"] = []
    return d


def missing(fields: dict, names=REQUIRED) -> list[str]:
    """Fields with no value. Text made only of spaces, and an infinite or not-a-number amount, count as no value."""
    def empty(v):
        return v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, float) and not math.isfinite(v))
    return [n for n in names if empty(fields.get(n))]
