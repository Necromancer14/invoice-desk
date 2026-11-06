"""Checks against ZATCA e-invoicing fields: Hijri dates, VAT categories, currency default, UBL XML and QR codes."""
from datetime import date

import pytest

from invoice_desk.default_rules import DEFAULT_RULES
from invoice_desk.extractors import RuleBasedExtractor
from invoice_desk.hijri import from_gregorian, to_gregorian
from invoice_desk.hijri_table import FIRST_YEAR, LAST_YEAR, MONTH_STARTS
from invoice_desk.rules import Ctx, decide, run_rules
from invoice_desk.textnorm import parse_date
from conftest import GOOD, TODAY

RULES = [dict(r, enabled=True) for r in DEFAULT_RULES]
BASE = dict(invoice_number="A-1", issue_date="2026-10-01", due_date="2026-11-01", seller_name="Acme", seller_vat="300000000000003",
            buyer_name="B", buyer_vat=None, currency="SAR", subtotal=1000.0, vat_amount=150.0, total=1150.0, qr_payload=None, line_items=[])


def outcome(**over):
    res = run_rules(RULES, dict(BASE, **over), Ctx(today=TODAY))
    return decide(res), {r["key"] for r in res if r["status"] == "fail" and r["severity"] != "info"}  # info rules only warn


# ---- Hijri dates ------------------------------------------------------------------------
@pytest.mark.parametrize("hijri, gregorian", [((1446, 9, 1), date(2025, 3, 1)),     # 1 Ramadan 1446
                                              ((1447, 1, 1), date(2025, 6, 26)),     # 1 Muharram 1447
                                              ((1447, 9, 1), date(2026, 2, 18))])    # 1 Ramadan 1447
def test_known_umm_al_qura_dates(hijri, gregorian):
    assert to_gregorian(*hijri) == gregorian and from_gregorian(gregorian) == hijri


def test_the_table_is_whole_and_months_are_29_or_30_days():
    assert len(MONTH_STARTS) == (LAST_YEAR - FIRST_YEAR + 1) * 12 + 1
    assert {b - a for a, b in zip(MONTH_STARTS, MONTH_STARTS[1:])} == {29, 30}


def test_round_trip_every_day_of_the_table():
    d, end = date(2000, 1, 1), date(2077, 1, 1)
    while d < end:
        assert to_gregorian(*from_gregorian(d)) == d
        d = date.fromordinal(d.toordinal() + 13)


@pytest.mark.parametrize("text, iso", [("1446-09-01", "2025-03-01"), ("01/09/1446 هـ", "2025-03-01"), ("١٤٤٧/٠١/٠١هـ", "2025-06-26"),
                                       ("٢٥/٠٥/١٤٤٨ هـ", "2026-11-05"), ("2026-10-01", "2026-10-01"), ("01/10/2026", "2026-10-01"),
                                       ("2026-10-01 (1448/04/20 هـ)", "2026-10-01")])
def test_parse_date_reads_hijri_and_gregorian(text, iso):
    assert parse_date(text) == iso


@pytest.mark.parametrize("text", ["30/02/1447", "1300-01-01", "1501-01-01", "2026-02-30", "soon"])
def test_impossible_or_out_of_range_dates_are_not_guessed(text):
    assert parse_date(text) is None


def test_a_future_hijri_date_is_flagged():
    status, fails = outcome(issue_date=parse_date("01/01/1449 هـ"))
    assert parse_date("01/01/1449 هـ") > TODAY.isoformat() and "issue-date" in fails and status == "needs_review"


def test_reader_converts_a_hijri_issue_date():
    text = GOOD.replace("Issue Date: 2026-10-01", "Issue Date: 20/04/1448 هـ").replace("Due Date: 2026-11-01\n", "")
    fields, _ = RuleBasedExtractor().parse(text)
    assert fields["issue_date"] == "2026-10-01"


# ---- VAT with zero-rated and exempt lines ------------------------------------------------
def lines(*rows):
    return [dict(description=f"line {n}", quantity=1, unit_price=amt, line_total=amt, **({"vat_category": c} if c else {}))
            for n, (amt, c) in enumerate(rows, 1)]


def test_zero_rated_line_carries_no_vat():
    items = lines((1000.0, None), (500.0, "Z"))
    assert outcome(subtotal=1500.0, vat_amount=150.0, total=1650.0, line_items=items) == ("approved", set())


def test_exempt_and_out_of_scope_lines_carry_no_vat():
    items = lines((1000.0, "S"), (300.0, "E"), (200.0, "O"))
    assert outcome(subtotal=1500.0, vat_amount=150.0, total=1650.0, line_items=items) == ("approved", set())


def test_vat_charged_on_a_zero_rated_line_is_caught():
    items = lines((1000.0, None), (500.0, "Z"))
    status, fails = outcome(subtotal=1500.0, vat_amount=225.0, total=1725.0, line_items=items)
    assert status == "rejected" and fails == {"vat-15"}


def test_all_zero_rated_means_no_vat():
    items = lines((800.0, "Z"))
    assert outcome(subtotal=800.0, vat_amount=0.0, total=800.0, line_items=items) == ("approved", set())


def test_without_categories_the_rule_works_as_before():
    assert outcome(line_items=lines((1000.0, None)))[0] == "approved"
    assert outcome(vat_amount=100.0, total=1100.0)[1] == {"vat-15"}


def test_reader_picks_up_line_categories_in_english_and_arabic():
    text = GOOD.replace("1. Consulting   2   500.00   1,000.00",
                        "1. Consulting   2   500.00   1,000.00\n2. Export freight (zero-rated)   1   400.00   400.00\n3. خدمات مالية (معفاة)   1   100.00   100.00")
    fields, _ = RuleBasedExtractor().parse(text)
    cats = [(i["description"], i.get("vat_category")) for i in fields["line_items"]]
    assert cats == [("Consulting", None), ("Export freight", "Z"), ("خدمات مالية", "E")]


# ---- currency and numbers ----------------------------------------------------------------
def test_no_currency_printed_means_sar_with_a_note():
    text = GOOD.replace("Currency: SAR\n", "").replace(" SAR", "")
    fields, notes = RuleBasedExtractor().parse(text)
    assert fields["currency"] == "SAR" and "No currency is printed, so SAR is assumed" in notes


def test_arabic_digits_and_separators_throughout():
    text = ("فاتورة ضريبية\nرقم الفاتورة: INV-٧\nتاريخ الإصدار: ٠١/١٠/٢٠٢٦\nالبائع: شركة\nالرقم الضريبي للبائع: ٣٠٠٠٠٠٠٠٠٠٠٠٠٠٣\nالعملة: ر.س\n"
            "المجموع الفرعي: ١٬٠٠٠٫٠٠ ر.س\nضريبة القيمة المضافة (15%): ١٥٠٫٠٠ ر.س\nالإجمالي شامل الضريبة: ١٬١٥٠٫٠٠ ر.س\n")
    fields, _ = RuleBasedExtractor().parse(text)
    assert (fields["invoice_number"], fields["issue_date"], fields["seller_vat"]) == ("INV-7", "2026-10-01", "300000000000003")
    assert (fields["subtotal"], fields["vat_amount"], fields["total"], fields["currency"]) == (1000.0, 150.0, 1150.0, "SAR")


# ---- UBL 2.1 XML ---------------------------------------------------------------------------
from fastapi.testclient import TestClient  # noqa: E402

from invoice_desk import qr, ubl  # noqa: E402
from invoice_desk.api import create_app  # noqa: E402
from invoice_desk.desk import Desk  # noqa: E402

UBL_FIELDS = dict(BASE, invoice_type="simplified", buyer_vat="311111111111113", subtotal=1500.0, vat_amount=150.0, total=1650.0,
                  line_items=[dict(description="Consulting", quantity=2, unit_price=500.0, line_total=1000.0),
                              dict(description="Export freight", quantity=1, unit_price=500.0, line_total=500.0, vat_category="Z")],
                  qr_payload=qr.encode("Acme", "300000000000003", "2026-10-01T09:30:00Z", 1650.0, 150.0))


def test_ubl_round_trip_reads_every_field():
    f = ubl.read(ubl.write(UBL_FIELDS).encode())
    for k in ("invoice_number", "issue_date", "due_date", "seller_name", "seller_vat", "buyer_vat", "currency",
              "subtotal", "vat_amount", "total", "qr_payload", "invoice_type"):
        assert f[k] == UBL_FIELDS[k], k
    assert [i.get("vat_category") for i in f["line_items"]] == ["S", "Z"]


def test_ubl_invoice_passes_the_same_rules():
    f = ubl.read(ubl.write(UBL_FIELDS).encode())
    res = run_rules(RULES, f, Ctx(today=TODAY))
    assert decide(res) == "approved", [r for r in res if r["status"] == "fail"]


def test_ubl_with_wrong_vat_is_caught():
    f = ubl.read(ubl.write(dict(UBL_FIELDS, vat_amount=225.0, total=1725.0, qr_payload=None)).encode())
    assert decide(run_rules(RULES, f, Ctx(today=TODAY))) == "rejected"


@pytest.mark.parametrize("xml", [
    b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Invoice>&e;</Invoice>',
    b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><Invoice>&b;</Invoice>',
    b'<!doctype Invoice SYSTEM "http://example.com/x.dtd"><Invoice/>',
])
def test_unsafe_xml_is_refused(xml):
    with pytest.raises(ubl.XmlError, match="DOCTYPE or ENTITY"):
        ubl.read(xml)


@pytest.mark.parametrize("xml, why", [(b"<Invoice><unclosed></Invoice>", "could not be read"), (b"<Order xmlns='x'/>", "not a UBL 2.1 Invoice")])
def test_malformed_or_other_xml_is_explained(xml, why):
    with pytest.raises(ubl.XmlError, match=why):
        ubl.read(xml)


@pytest.fixture
def client(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=1000))
    return c, {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "admin"}).json()["token"]}


@pytest.mark.parametrize("ctype", ["application/xml", "text/xml", ""])
def test_xml_upload_is_read_directly_in_any_mode(client, ctype):
    c, h = client
    for mode in ("rules", "ai"):
        r = c.post("/api/runs", files={"files": ("inv.xml", ubl.write(UBL_FIELDS).encode(), ctype)}, data={"mode": mode},
                   headers={**h, "X-LLM-Provider": "gemini", "X-LLM-Key": "k"} if mode == "ai" else h)
        assert r.status_code == 200, r.text
        run = c.get(f"/api/runs/{r.json()['ids'][0]}", headers=h).json()
        assert run["extractor"] == "ubl-xml" and run["status"] == "approved", (mode, run["status"], run["results"])
        c.post("/api/admin/reset", json={}, headers=h)


def test_unsafe_xml_upload_is_refused(client):
    c, h = client
    r = c.post("/api/runs", files={"files": ("x.xml", b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Invoice>&e;</Invoice>', "application/xml")}, headers=h)
    assert r.status_code == 415 and "DOCTYPE or ENTITY" in r.json()["detail"]


def test_broken_xml_upload_fails_with_a_plain_message(client):
    c, h = client
    rid = c.post("/api/runs", files={"files": ("x.xml", b"<Invoice><broken></Invoice>", "application/xml")}, headers=h).json()["ids"][0]
    run = c.get(f"/api/runs/{rid}", headers=h).json()
    assert run["status"] == "failed" and run["error"].startswith("This XML file could not be read")
