"""The fields the desk extracts from an invoice, in one place."""
from __future__ import annotations

SCALARS = ["invoice_number", "issue_date", "due_date", "seller_name", "seller_vat", "buyer_name",
           "buyer_vat", "currency", "subtotal", "vat_amount", "total", "qr_payload"]
NUMERIC = {"subtotal", "vat_amount", "total"}
FIELDS = SCALARS + ["line_items"]
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
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": ["number", "null"]},
                    "unit_price": {"type": ["number", "null"]},
                    "line_total": {"type": ["number", "null"]},
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
    d["line_items"] = []
    return d


def missing(fields: dict, names=REQUIRED) -> list[str]:
    return [n for n in names if fields.get(n) in (None, "")]
