"""Hijri (Umm al-Qura) dates to Gregorian and back, from 1420 to 1500 AH (about 1999 to 2077).

The month table comes from ICU's islamic-umalqura calendar (see tools/build_hijri_table.mjs). Dates outside the table
are not guessed: the functions return None.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import date, timedelta

from .hijri_table import FIRST_YEAR, LAST_YEAR, MONTH_STARTS

_EPOCH = date(1970, 1, 1)


def to_gregorian(year: int, month: int, day: int) -> date | None:
    """The Gregorian date of a Hijri date, or None if it is outside the table or the day does not exist."""
    if not (FIRST_YEAR <= year <= LAST_YEAR and 1 <= month <= 12 and day >= 1):
        return None
    i = (year - FIRST_YEAR) * 12 + month - 1
    length = MONTH_STARTS[i + 1] - MONTH_STARTS[i]
    if day > length:
        return None
    return _EPOCH + timedelta(days=MONTH_STARTS[i] + day - 1)


def from_gregorian(d: date) -> tuple[int, int, int] | None:
    """(year, month, day) in the Hijri calendar, or None outside the table."""
    n = (d - _EPOCH).days
    if not (MONTH_STARTS[0] <= n < MONTH_STARTS[-1]):
        return None
    i = bisect_right(MONTH_STARTS, n) - 1
    return FIRST_YEAR + i // 12, i % 12 + 1, n - MONTH_STARTS[i] + 1
