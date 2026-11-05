"""The TLV payload that Saudi simplified tax invoices carry in their QR code.

Tags 1 to 5: seller name, VAT number, timestamp, total with VAT, VAT amount.
Each entry is tag (1 byte), length (1 byte), value (UTF-8). The whole thing is base64.
"""
from __future__ import annotations

import base64

TAGS = {1: "seller_name", 2: "seller_vat", 3: "timestamp", 4: "total", 5: "vat_amount"}


def encode(seller_name: str, vat: str, timestamp: str, total: float, vat_amount: float) -> str:
    out = bytearray()
    for tag, value in enumerate([seller_name, vat, timestamp, f"{total:.2f}", f"{vat_amount:.2f}"], start=1):
        raw = value.encode("utf-8")
        if len(raw) > 255:
            raise ValueError("TLV value too long")
        out += bytes([tag, len(raw)]) + raw
    return base64.b64encode(bytes(out)).decode("ascii")


def decode(payload: str | None) -> dict | None:
    if not payload:
        return None
    try:
        raw = base64.b64decode(payload.strip(), validate=True)
    except Exception:
        return None
    out: dict = {}
    i = 0
    while i + 2 <= len(raw):
        tag, length = raw[i], raw[i + 1]
        value = raw[i + 2 : i + 2 + length]
        if len(value) != length:
            return None
        out[TAGS.get(tag, f"tag{tag}")] = value.decode("utf-8", "replace")
        i += 2 + length
    return out or None
