import pytest

from invoice_desk import qr
from invoice_desk.textnorm import normalize, parse_date, to_number


@pytest.mark.parametrize("raw,want", [("1,234.50", 1234.5), ("١٬٢٣٤٫٥٠ ر.س", 1234.5), ("1.234,50", 1234.5), ("SAR 99", 99.0),
                                       ("", None), (None, None), ("abc", None), (12, 12.0)])
def test_to_number(raw, want):
    assert to_number(raw) == want


@pytest.mark.parametrize("raw,want", [("2026-03-04", "2026-03-04"), ("04/03/2026", "2026-03-04"), ("٠٤/٠٣/٢٠٢٦", "2026-03-04"),
                                       ("31/02/2026", None), ("nonsense", None), (None, None)])
def test_parse_date(raw, want):
    assert parse_date(normalize(raw) if raw else raw) == want


def test_normalize_strips_bidi_marks():
    assert normalize("‏رقم ١٢٣") == "رقم 123"


def test_qr_roundtrip():
    payload = qr.encode("شركة الاختبار", "300000000000003", "2026-10-01T09:30:00Z", 1150.0, 150.0)
    d = qr.decode(payload)
    assert d["seller_name"] == "شركة الاختبار" and d["seller_vat"] == "300000000000003"
    assert float(d["total"]) == 1150.0 and float(d["vat_amount"]) == 150.0


def test_qr_garbage_is_none():
    assert qr.decode("not base64 !!") is None and qr.decode(None) is None
