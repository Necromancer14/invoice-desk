"""Edge cases found in the self-audit: digits, spaces, signs and sizes the rules must handle."""
import math

import pytest

from invoice_desk.default_rules import DEFAULT_RULES
from invoice_desk.rules import RULE_TYPES, Ctx, decide, run_rules, validate_rule
from invoice_desk.schema import missing
from invoice_desk.textnorm import number_key, to_number, vat_key
from conftest import GOOD, TODAY

BASE = dict(invoice_number="A-1", issue_date="2026-10-01", due_date="2026-11-01", seller_name="Acme", seller_vat="300000000000003",
            buyer_name="B", buyer_vat=None, currency="SAR", subtotal=1000.0, vat_amount=150.0, total=1150.0, qr_payload=None, line_items=[])
RULES = [dict(r, enabled=True) for r in DEFAULT_RULES]


def outcome(**over):
    res = run_rules(RULES, dict(BASE, **over), Ctx(today=TODAY))
    return decide(res), {r["key"] for r in res if r["status"] == "fail"}


def test_baseline_is_approved():
    assert outcome() == ("approved", set())


@pytest.mark.parametrize("vat", ["٣٠٠٠٠٠٠٠٠٠٠٠٠٠٣", "۳۰۰۰۰۰۰۰۰۰۰۰۰۰۳", "300 000 000 000 003", " 300000000000003 ", "300-000-000-000-003"])
def test_a_valid_vat_number_written_differently_is_still_valid(vat):
    assert outcome(seller_vat=vat) == ("approved", set())


@pytest.mark.parametrize("vat", ["30000000000000", "400000000000003", "3000000000000O3", "٣٠٠٠"])
def test_a_malformed_vat_number_is_still_rejected(vat):
    assert outcome(seller_vat=vat)[0] == "rejected"


def test_negative_total_goes_to_review():
    status, fails = outcome(subtotal=-1000.0, vat_amount=-150.0, total=-1150.0)
    assert status == "needs_review" and fails == {"total-not-negative"}


def test_zero_total_is_fine():
    assert outcome(subtotal=0.0, vat_amount=0.0, total=0.0) == ("approved", set())


def test_huge_amounts_keep_their_arithmetic():
    status, fails = outcome(subtotal=123456789012345.67, vat_amount=18518518351851.85, total=141975307364197.52)
    assert fails == {"limit-50k"}  # only the high-value rule, no false arithmetic failure from rounding


def test_whitespace_only_fields_count_as_missing():
    status, fails = outcome(seller_name="   ", invoice_number="\t")
    assert "required" in fails
    assert missing({"a": "  ", "b": "x", "c": None, "d": 0}, ["a", "b", "c", "d"]) == ["a", "c"]


def test_currency_with_spaces_or_lower_case_is_sar():
    assert outcome(currency=" sar ") == ("approved", set())


def test_arabic_indic_amounts():
    assert outcome(subtotal="١٬٠٠٠٫٠٠", vat_amount="١٥٠٫٠٠", total="١٬١٥٠٫٠٠") == ("approved", set())


@pytest.mark.parametrize("text, value", [("(100.00)", -100.0), ("SAR (1,150.00)", -1150.0), ("-12.5", -12.5), ("1,150.00", 1150.0),
                                         ("١٬١٥٠٫٠٠", 1150.0), ("inf", None), ("nan", None), ("", None), ("abc", None)])
def test_to_number(text, value):
    assert to_number(text) == value


def test_brackets_around_part_of_a_value_do_not_make_it_negative():
    assert to_number("150.00 (15%)") > 0


def test_non_finite_numbers_count_as_missing():
    assert to_number(float("inf")) is None and to_number(float("nan")) is None and to_number(math.pi) == math.pi
    status, fails = outcome(total=float("inf"))
    assert status == "needs_review" and "required" in fails


def test_keys_for_comparing():
    assert vat_key("٣٠٠ ٠٠٠ ٠٠٠ ٠٠٠ ٠٠٣") == "300000000000003"
    assert number_key("  acm-2026-0001 ") == number_key("ACM-2026-0001") == "acm-2026-0001"


def test_amount_limit_min_and_open_ends():
    validate_rule(dict(name="x", type="amount_limit", severity="review", params={"field": "total", "min": None, "max": None}))
    validate_rule(dict(name="x", type="amount_limit", severity="review", params={"field": "total", "min": "", "max": 10}))
    with pytest.raises(ValueError, match="min must be a number"):
        validate_rule(dict(name="x", type="amount_limit", severity="review", params={"field": "total", "min": "abc"}))
    rule = dict(key="r", name="r", type="amount_limit", severity="review", enabled=True, params={"field": "total", "min": 10, "max": None})
    assert run_rules([rule], dict(BASE, total=5), Ctx(today=TODAY))[0]["status"] == "fail"
    assert run_rules([rule], dict(BASE, total=10**12), Ctx(today=TODAY))[0]["status"] == "pass"
    assert any(p["name"] == "min" for p in RULE_TYPES["amount_limit"]["params"])


def test_duplicate_found_despite_case_spacing_and_digits(desk):
    first = desk.submit("a.txt", GOOD.encode(), "text/plain", "t")
    assert desk.get_run(first)["status"] == "approved"
    again = GOOD.replace("ACM-2026-0001", "acm-2026-0001").replace("300000000000003", "٣٠٠٠٠٠٠٠٠٠٠٠٠٠٣")
    rid = desk.submit("b.txt", again.encode(), "text/plain", "t")
    run = desk.get_run(rid)
    assert run["status"] == "rejected" and "duplicate" in {r["key"] for r in run["results"] if r["status"] == "fail"}


def test_same_invoice_number_in_another_currency_is_still_a_duplicate(desk):
    """Deliberate: the same seller and invoice number is the same invoice, whatever currency it is printed in."""
    desk.submit("a.txt", GOOD.encode(), "text/plain", "t")
    rid = desk.submit("b.txt", GOOD.replace("SAR", "USD").encode(), "text/plain", "t")
    assert "duplicate" in {r["key"] for r in desk.get_run(rid)["results"] if r["status"] == "fail"}


def test_different_sellers_with_the_same_number_are_not_duplicates(desk):
    desk.submit("a.txt", GOOD.encode(), "text/plain", "t")
    rid = desk.submit("b.txt", GOOD.replace("300000000000003", "311111111111113").encode(), "text/plain", "t")
    assert "duplicate" not in {r["key"] for r in desk.get_run(rid)["results"] if r["status"] == "fail"}
