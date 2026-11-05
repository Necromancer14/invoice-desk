"""Normalising text, numbers and dates from English and Arabic invoices."""
from __future__ import annotations

import re
from datetime import date

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"), None)


def normalize(text: str) -> str:
    """Arabic-Indic digits to ASCII, Arabic separators to ASCII, drop bidi marks."""
    text = text.translate(_DIGITS).translate(_INVISIBLE)
    return text.replace("٫", ".").replace("٬", ",").replace("،", ",")


def to_number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    t = re.sub(r"[^\d.,\-]", "", normalize(str(value)))
    t = t.strip(".,")
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", t) else t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DMY = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})")


def parse_date(value) -> str | None:
    """Return an ISO date. Day-first for DD/MM/YYYY, which is how Saudi invoices write it."""
    if not value:
        return None
    t = normalize(str(value))
    try:
        m = _ISO.search(t)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3])).isoformat()
        m = _DMY.search(t)
        if m:
            return date(int(m[3]), int(m[2]), int(m[1])).isoformat()
    except ValueError:
        return None
    return None
