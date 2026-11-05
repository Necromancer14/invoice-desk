from datetime import date

import pytest

from invoice_desk import qr
from invoice_desk.default_rules import DEFAULT_RULES
from invoice_desk.rules import RULE_TYPES, Ctx, decide, run_rules, validate_expression, validate_rule

TODAY = date(2026, 11, 5)


def inv(**kw):
    base = dict(invoice_number="A-1", issue_date="2026-10-01", due_date="2026-11-01", seller_name="Acme", seller_vat="300000000000003",
                buyer_name="B", buyer_vat=None, currency="SAR", subtotal=1000.0, vat_amount=150.0, total=1150.0, qr_payload=None,
                line_items=[dict(description="x", quantity=2, unit_price=500.0, line_total=1000.0)])
    base.update(kw)
    return base


def status(rules, f, **ctx):
    return {x["key"]: x["status"] for x in run_rules(rules, f, Ctx(today=TODAY, **ctx))}


def one(type_, params=None, severity="reject"):
    return [dict(key="r", name="r", type=type_, params=params or {}, severity=severity, enabled=True, message="")]


def test_default_rules_approve_a_good_invoice():
    assert decide(run_rules(DEFAULT_RULES, inv(), Ctx(today=TODAY))) == "approved"


@pytest.mark.parametrize("vat,ok", [("300000000000003", True), ("400000000000003", False), ("30000000000003", False), ("300000000000007", False)])
def test_vat_number(vat, ok):
    assert status(one("vat_number"), inv(seller_vat=vat))["r"] == ("pass" if ok else "fail")


def test_missing_vat_is_left_to_the_required_fields_rule():
    assert status(one("vat_number"), inv(seller_vat=None))["r"] == "skip"
    assert status(one("vat_number", {"field": "buyer_vat", "optional": True}), inv())["r"] == "pass"


def test_vat_rate_and_totals():
    assert status(one("vat_rate", {"rate": 0.15}), inv(vat_amount=100.0, total=1100.0))["r"] == "fail"
    assert status(one("totals"), inv(total=1200.0))["r"] == "fail"
    assert status(one("totals"), inv())["r"] == "pass"


def test_line_math():
    bad = inv(line_items=[dict(description="x", quantity=2, unit_price=500.0, line_total=900.0)])
    assert status(one("line_math"), bad)["r"] == "fail"


def test_dates():
    assert status(one("date_valid", {"field": "issue_date", "not_future": True}), inv(issue_date="2031-01-01"))["r"] == "fail"
    assert status(one("date_valid", {"field": "issue_date", "not_future": True}), inv(issue_date="not a date"))["r"] == "fail"
    assert status(one("date_order", {"first": "issue_date", "second": "due_date"}), inv(due_date="2026-09-01"))["r"] == "fail"


def test_currency_and_limit():
    assert status(one("currency", {"allowed": ["SAR"]}), inv(currency="USD"))["r"] == "fail"
    assert status(one("amount_limit", {"field": "total", "max": 1000}), inv())["r"] == "fail"


def test_required_fields():
    assert status(one("required_fields", {"fields": ["seller_name", "buyer_name"]}), inv(buyer_name=None))["r"] == "fail"


def test_qr_match():
    ok = qr.encode("Acme", "300000000000003", "2026-10-01T09:30:00Z", 1150.0, 150.0)
    assert status(one("qr_match"), inv(qr_payload=ok))["r"] == "pass"
    bad = qr.encode("Acme", "300000000000003", "2026-10-01T09:30:00Z", 1400.0, 150.0)
    assert status(one("qr_match"), inv(qr_payload=bad))["r"] == "fail"
    assert status(one("qr_match"), inv())["r"] == "skip"


def test_qr_name_in_other_script_is_not_a_mismatch():
    p = qr.encode("Acme Trading", "300000000000003", "2026-10-01T09:30:00Z", 1150.0, 150.0)
    assert status(one("qr_match"), inv(qr_payload=p, seller_name="شركة أكمي"))["r"] == "pass"


def test_duplicate_and_confidence():
    assert status(one("duplicate"), inv(), is_duplicate=lambda v, n: True)["r"] == "fail"
    assert status(one("min_confidence", {"threshold": 0.9}), inv(), confidence=0.5)["r"] == "fail"


def test_severity_decides():
    f = inv(currency="USD")
    assert decide(run_rules(one("currency", {"allowed": ["SAR"]}, "review"), f, Ctx(today=TODAY))) == "needs_review"
    assert decide(run_rules(one("currency", {"allowed": ["SAR"]}, "reject"), f, Ctx(today=TODAY))) == "rejected"
    assert decide(run_rules(one("currency", {"allowed": ["SAR"]}, "info"), f, Ctx(today=TODAY))) == "approved"


def test_disabled_rule_is_skipped():
    r = one("currency", {"allowed": ["SAR"]})
    r[0]["enabled"] = False
    assert run_rules(r, inv(currency="USD"), Ctx(today=TODAY)) == []


def test_every_rule_type_has_ui_metadata():
    for k, v in RULE_TYPES.items():
        assert v["label"] and v["description"] and isinstance(v["params"], list), k


# ---- expression safety ------------------------------------------------------------------
@pytest.mark.parametrize("expr", ["__import__('os').system('id')", "total.__class__", "open('/etc/passwd')", "[x for x in total]",
                                  "lambda: 1", "total ** 9 ** 9", "eval('1')", "(1).real", "unknown_field > 1", "total[0]", "a := 1",
                                  "f'{total}'", "x" * 400, ""])
def test_hostile_expressions_are_rejected(expr):
    with pytest.raises(ValueError):
        validate_expression(expr)


def test_expressions_evaluate():
    r = one("expression", {"expr": "total > 1000 and currency == 'SAR' and item_count == 1"})
    assert status(r, inv())["r"] == "pass"
    assert status(one("expression", {"expr": "sum_of(line_items, 'line_total') == subtotal"}), inv())["r"] == "pass"
    assert status(one("expression", {"expr": "contains(seller_name, 'acm')"}), inv())["r"] == "pass"
    assert status(one("expression", {"expr": "total / 0 > 1"}), inv())["r"] == "fail"
    assert status(one("expression", {"expr": "total > 1"}), inv(total=None))["r"] == "fail"


def test_validate_rule_messages():
    base = dict(key="k", name="n", type="vat_rate", severity="reject", params={})
    validate_rule(base)
    for bad, text in [(dict(type="nope"), "unknown rule type"), (dict(severity="boom"), "severity"), (dict(name=" "), "name"),
                      (dict(type="regex", params={"field": "invoice_number", "pattern": "("}), "pattern"),
                      (dict(type="vat_rate", params={"rate": "x"}), "number"), (dict(type="expression", params={"expr": "open(1)"}), "helper"),
                      (dict(type="required_fields", params={"fields": ["nope"]}), "unknown fields")]:
        with pytest.raises(ValueError, match=text):
            validate_rule({**base, **bad})
