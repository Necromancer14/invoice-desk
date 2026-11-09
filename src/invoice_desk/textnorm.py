"""Normalising text, numbers and dates from English and Arabic invoices."""
from __future__ import annotations

import math
import re
from datetime import date

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_INVISIBLE = dict.fromkeys(map(ord, "‎‏‪‫‬‭‮⁦⁧⁨⁩﻿"), None)


def normalize(text: str) -> str:
    """Arabic-Indic digits to ASCII, Arabic separators to ASCII, drop bidi marks."""
    text = text.translate(_DIGITS).translate(_INVISIBLE)
    return text.replace("٫", ".").replace("٬", ",").replace("،", ",")


def vat_key(value) -> str:
    """A VAT number as digits only: Arabic-Indic digits converted, spaces and separators dropped."""
    return re.sub(r"[\s\-.]", "", normalize(str(value or "")))


def number_key(value) -> str:
    """An invoice number for comparing: digits normalised, spaces collapsed, case ignored."""
    return re.sub(r"\s+", " ", normalize(str(value or ""))).strip().casefold()


def to_number(value) -> float | None:
    """A number from text such as "SAR 1,150.00", "١٬١٥٠٫٠٠" or "(100.00)" (accounting negative).
    Infinite and not-a-number values count as missing."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = normalize(str(value)).strip()
    # the whole amount in brackets, a currency code around it allowed: "(100.00)", "SAR (1,150.00)", not "150.00 (15%)"
    negative = bool(re.fullmatch(r"[^\d()]*\(\s*[\d.,\s]*\d[\d.,\s]*\)[^\d()]*", text))
    t = re.sub(r"[^\d.,\-]", "", text)
    t = t.strip(".,")
    if not re.search(r"\d", t):
        return None
    if "," in t and "." in t:
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") else t.replace(",", "")
    elif "," in t:
        t = t.replace(",", "") if re.fullmatch(r"-?\d{1,3}(,\d{3})+", t) else t.replace(",", ".")
    try:
        n = float(t)
    except ValueError:
        return None
    if not math.isfinite(n):
        return None
    return -abs(n) if negative else n


_ISO = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})")
_DMY = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})")
# a year from 1300 to 1600 can only be Hijri on an invoice; هـ / AH / H marks it too
_HIJRI_YEARS = range(1300, 1601)


def parse_date(value) -> str | None:
    """Return an ISO (Gregorian) date. Day-first for DD/MM/YYYY, which is how Saudi invoices write it.
    Hijri dates such as 15/04/1448 هـ or ١٤٤٨-٠٤-١٥ are converted with the Umm al-Qura calendar."""
    if not value:
        return None
    t = normalize(str(value))
    m = _ISO.search(t)
    ymd = (int(m[1]), int(m[2]), int(m[3])) if m else None
    if not ymd:
        m = _DMY.search(t)
        ymd = (int(m[3]), int(m[2]), int(m[1])) if m else None
    if not ymd:
        return None
    if ymd[0] in _HIJRI_YEARS:
        from .hijri import to_gregorian
        g = to_gregorian(*ymd)
        return g.isoformat() if g else None
    try:
        return date(*ymd).isoformat()
    except ValueError:
        return None
