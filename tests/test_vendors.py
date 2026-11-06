"""Vendor master and purchase orders: IBAN and VAT validation, name matching, the five rules, the desk and the API."""
import pytest
from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.default_rules import DEFAULT_RULES
from invoice_desk.desk import Desk, DeskError
from invoice_desk.extractors import RuleBasedExtractor
from invoice_desk.rules import Ctx, decide, run_rules
from invoice_desk.ubl import read as read_ubl, write as write_ubl
from invoice_desk.vendors import (VendorBook, clean_vendor, iban_problem, name_key, name_score, name_tokens, po_match,
                                  read_csv, saudi_iban)
from conftest import GOOD, TODAY

IBAN_A = saudi_iban("80", "000123456789012345")
IBAN_B = saudi_iban("10", "000000000000000777")
RAJHI = dict(id=1, name_en="Al Rajhi Trading Co.", name_ar="شركة الراجحي للتجارة", vat="310000000000003", iban=IBAN_A,
             currency="SAR", status="approved")
NAJD = dict(id=2, name_en="Najd Office Supplies", name_ar=None, vat="320000000000003", iban=None, currency="SAR", status="blocked")
BOOK = VendorBook([RAJHI, NAJD])
PO = dict(po_number="PO-100", vendor_id=1, vendor_name="Al Rajhi Trading Co.", amount=1150.0, currency="SAR", status="open")
RULES = [dict(r, enabled=True) for r in DEFAULT_RULES]
BASE = dict(invoice_number="A-1", issue_date="2026-10-01", due_date="2026-11-01", seller_name="Al Rajhi Trading",
            seller_vat="310000000000003", buyer_name="B", buyer_vat=None, currency="SAR", subtotal=1000.0, vat_amount=150.0,
            total=1150.0, qr_payload=None, iban=IBAN_A, po_number="PO-100", line_items=[])


def outcome(book=BOOK, **over):
    ctx = Ctx(today=TODAY, vendors=book, po_for=lambda n: PO if n == "PO-100" else None)
    res = run_rules(RULES, dict(BASE, **over), ctx)
    return decide(res), {r["key"] for r in res if r["status"] == "fail" and r["severity"] != "info"}, res


# ---- IBAN and VAT ---------------------------------------------------------------------------------
def test_saudi_iban_is_24_characters_and_passes_mod_97():
    assert len(IBAN_A) == 24 and IBAN_A.startswith("SA") and iban_problem(IBAN_A) is None
    assert iban_problem("SA03 8000 0000 6080 1016 7519") is None       # a published example, with spaces
    assert iban_problem("GB82WEST12345698765432") is None              # other countries: mod-97 only


@pytest.mark.parametrize("bad, words", [(IBAN_A[:-1] + str((int(IBAN_A[-1]) + 1) % 10), "mod-97"), ("SA12", "IBAN form"),
                                        ("SA0380000000608010167519X", "24 characters"), ("", "empty"), ("1234567890123456", "IBAN form")])
def test_bad_ibans_say_what_is_wrong(bad, words):
    assert words in iban_problem(bad)


def test_vendor_validation():
    v, errors = clean_vendor(dict(name_en=" Acme ", vat="3000 0000 0000 003", iban=IBAN_A.lower(), currency="sar"))
    assert errors == [] and v["vat"] == "300000000000003" and v["iban"] == IBAN_A and v["currency"] == "SAR" and v["status"] == "approved"
    _, errors = clean_vendor(dict(vat="123", iban="SA00", currency="12", status="maybe"))
    assert len(errors) == 5


# ---- names --------------------------------------------------------------------------------------------
@pytest.mark.parametrize("a, b", [("Al Rajhi Trading", "AL-RAJHI  trading co. LLC"), ("الراجحي للتجارة", "شركة الراجحي للتجارة ذ.م.م"),
                                  ("مؤسسة نجد", "موسسة نجد"), ("الراجحى", "الراجحي"), ("شركة الأمل", "شركه الامل"),
                                  ("مَكْتَبَة", "مكتبة"), ("مكـــتبة", "مكتبة")])
def test_names_that_mean_the_same_normalise_the_same(a, b):
    assert name_key(a) == name_key(b) and name_key(a)


def test_score_is_one_for_same_words_and_lower_otherwise():
    assert name_score(name_tokens("Trading Rajhi"), name_tokens("Rajhi Trading")) == 1.0
    assert 0.5 < name_score(name_tokens("Najd Office Supply"), name_tokens("Najd Office Supplies")) < 0.85
    assert name_score([], ["x"]) == 0.0


def test_english_and_arabic_invoice_names_map_to_one_vendor():
    for name in ("Al Rajhi Trading", "الراجحي للتجارة", "AL RAJHI TRADING LLC"):
        m = BOOK.match({"seller_name": name})
        assert m["vendor"]["id"] == 1 and m["score"] == 1.0 and "normalising" in m["why"]


def test_close_but_not_enough_gives_suggestions_not_a_match():
    m = BOOK.match({"seller_name": "Najd Office Supply"})
    assert m["vendor"] is None and m["suggestions"][0]["id"] == 2 and "closest" in m["why"]
    assert BOOK.match({"seller_name": "Najd Office Supply"}, min_score=0.6)["vendor"]["id"] == 2


def test_vat_number_identifies_the_vendor_when_the_name_does_not():
    m = BOOK.match({"seller_name": "RT Co", "seller_vat": "310000000000003"})
    assert m["vendor"]["id"] == 1 and m["matched_on"] == "VAT number"


def test_ties_go_to_the_lower_id():
    book = VendorBook([dict(id=5, name_en="Same Name"), dict(id=3, name_en="Same Name")])
    assert book.match({"seller_name": "same name"})["vendor"]["id"] == 3


def test_linked_names_match():
    book = VendorBook([RAJHI], [dict(vendor_id=1, alias="RTC Riyadh")])
    m = book.match({"seller_name": "rtc riyadh"})
    assert m["vendor"]["id"] == 1 and m["matched_on"] == "linked name"


# ---- the rules -------------------------------------------------------------------------------------------
def test_a_clean_invoice_from_a_known_vendor_is_approved():
    decision, failed, res = outcome()
    assert decision == "approved" and not failed
    assert {r["key"]: r["status"] for r in res}["po-amount"] == "pass"


def test_unknown_vendor_goes_to_review():
    decision, failed, _ = outcome(seller_name="Nobody Known", seller_vat="300000000000003")
    assert decision == "needs_review" and "vendor-known" in failed


def test_blocked_vendor_is_rejected():
    decision, failed, _ = outcome(seller_name="Najd Office Supplies", seller_vat="320000000000003", iban=None, po_number=None)
    assert decision == "rejected" and "vendor-blocked" in failed


def test_vat_number_differing_from_the_vendor_master_goes_to_review():
    decision, failed, _ = outcome(seller_vat="300000000000003")
    assert decision == "needs_review" and failed == {"vendor-vat"}


def test_changed_iban_is_high_risk_review_with_a_fraud_warning():
    decision, failed, res = outcome(iban=IBAN_B)
    r = next(x for x in res if x["key"] == "vendor-iban")
    assert decision == "needs_review" and failed == {"vendor-iban"}
    assert r["risk"] == "high" and "High risk" in r["detail"] and "fraud" in r["detail"]


def test_invalid_iban_on_the_invoice_is_high_risk():
    _, failed, res = outcome(iban="SA0000000000000000000000")
    assert "vendor-iban" in failed and next(x for x in res if x["key"] == "vendor-iban")["risk"] == "high"


def test_above_the_po_goes_to_review_within_tolerance_passes():
    assert outcome(subtotal=1008.7, vat_amount=151.3, total=1160.0)[0] == "approved"   # within 1%
    decision, failed, _ = outcome(total=1200.0, subtotal=1043.48, vat_amount=156.52)
    assert decision == "needs_review" and "po-amount" in failed


def test_vendor_rules_skip_without_a_vendor_master_or_fields():
    decision, failed, res = outcome(book=VendorBook([]), seller_name="Nobody")
    keys = {"vendor-known", "vendor-blocked", "vendor-vat", "vendor-iban"}
    assert decision == "approved" and not failed
    assert all(r["status"] == "skip" for r in res if r["key"] in keys - {"vendor-iban"})
    _, _, res = outcome(iban=None, po_number=None)
    assert {r["key"]: r["status"] for r in res}["vendor-iban"] == "skip" and {r["key"]: r["status"] for r in res}["po-amount"] == "skip"


def test_po_match_statuses():
    f = dict(BASE)
    assert po_match(dict(f, po_number=None), None, RAJHI)["status"] == "no_po"
    assert po_match(dict(f, po_number="PO-9"), None, RAJHI)["status"] == "not_found"
    assert po_match(f, PO, RAJHI)["status"] == "matched"
    assert po_match(f, PO, NAJD)["status"] == "vendor_mismatch"
    assert po_match(dict(f, currency="USD"), PO, RAJHI)["status"] == "currency_mismatch"
    assert po_match(dict(f, total=2000), PO, RAJHI)["status"] == "over"
    assert po_match(f, dict(PO, status="closed"), RAJHI)["status"] == "closed"
    assert po_match(dict(f, subtotal=1000), PO, RAJHI, 0, "subtotal")["status"] == "matched"


# ---- readers ----------------------------------------------------------------------------------------------
def test_text_reader_finds_iban_and_po_number():
    text = GOOD.replace("Currency: SAR", f"Currency: SAR\nIBAN: {IBAN_A[:4]} {IBAN_A[4:8]} {IBAN_A[8:]}\nPO Number: PO-100")
    f = RuleBasedExtractor().extract(text.encode(), "text/plain").fields
    assert f["iban"] == IBAN_A and f["po_number"] == "PO-100"
    ar = GOOD.replace("Currency: SAR", f"Currency: SAR\nرقم الآيبان: {IBAN_A}\nرقم أمر الشراء: PO-7")
    f = RuleBasedExtractor().extract(ar.encode(), "text/plain").fields
    assert f["iban"] == IBAN_A and f["po_number"] == "PO-7"


def test_ubl_round_trips_iban_and_po_number():
    f = read_ubl(write_ubl(dict(BASE, line_items=[])).encode())
    assert f["iban"] == IBAN_A and f["po_number"] == "PO-100"


# ---- the desk -------------------------------------------------------------------------------------------------
VENDOR_CSV = f"""Name EN,Name AR,VAT Number,IBAN,Currency,Status
Al Rajhi Trading Co.,شركة الراجحي للتجارة,310000000000003,{IBAN_A},SAR,approved
Najd Office Supplies,,320000000000003,,SAR,blocked
Broken,,123,SA00,SAR,approved
"""
PO_CSV = "po_number,vendor,amount,currency,status\nPO-100,Al Rajhi Trading,1150,SAR,open\nPO-200,320000000000003,500,SAR,closed\n,x,1,SAR,open\n"


def text_with(**f):
    return GOOD.replace("Seller: Acme Trading", f"Seller: {f.get('seller', 'Acme Trading')}").replace(
        "Seller VAT No: 300000000000003", f"Seller VAT No: {f.get('vat', '300000000000003')}").replace(
        "Currency: SAR", f"Currency: SAR\nIBAN: {f.get('iban', IBAN_A)}\nPO Number: {f.get('po', 'PO-100')}").encode()


def test_import_add_edit_delete(desk):
    r = desk.import_vendors(VENDOR_CSV, "a")
    assert (r["added"], r["updated"], r["error_count"]) == (2, 0, 1) and r["errors"][0]["row"] == 4
    assert desk.import_vendors(VENDOR_CSV, "a")["updated"] == 2           # same VAT numbers update, not duplicate
    vs = desk.list_vendors()
    assert len(vs) == 2
    najd = next(v for v in vs if v["vat"] == "320000000000003")
    desk.save_vendor(dict(najd, status="approved"), "a", najd["id"])
    assert desk.db.one("SELECT status FROM vendors WHERE id=?", (najd["id"],))["status"] == "approved"
    with pytest.raises(DeskError, match="already has VAT"):
        desk.save_vendor(dict(name_en="Copy", vat="310000000000003"), "a")
    with pytest.raises(DeskError, match="IBAN"):
        desk.save_vendor(dict(name_en="Bad", iban="SA1"), "a")
    p = desk.import_pos(PO_CSV, "a")
    assert (p["added"], p["error_count"]) == (2, 1)
    pos = {x["po_number"]: x for x in desk.list_pos()}
    assert pos["PO-100"]["vendor_id"] and pos["PO-200"]["vendor_id"] == najd["id"]      # by name and by VAT number
    desk.delete_vendor(najd["id"], "a")
    assert len(desk.list_vendors()) == 1 and desk.po_by_number("po-200")["vendor_id"] is None
    assert any(a["action"] == "vendor.import" for a in desk.db.all("SELECT action FROM audit"))


def test_run_detail_shows_vendor_and_po_match(desk):
    desk.import_vendors(VENDOR_CSV, "a")
    desk.import_pos(PO_CSV, "a")
    rid = desk.submit("a.txt", text_with(seller="Al Rajhi Trading", vat="310000000000003"), "text/plain", "r")
    run = desk.get_run(rid)
    assert run["status"] == "approved" and run["vendor_match"]["vendor"]["name_en"] == "Al Rajhi Trading Co."
    assert run["po_match"]["status"] == "matched"


def test_changed_iban_shows_high_risk_in_the_queue(desk):
    desk.import_vendors(VENDOR_CSV, "a")
    rid = desk.submit("a.txt", text_with(seller="Al Rajhi Trading", vat="310000000000003", iban=IBAN_B, po="none"), "text/plain", "r")
    q = desk.review_queue()
    assert q[0]["id"] == rid and q[0]["high_risk"] is True


def test_link_vendor_remembers_the_name_and_rechecks(desk):
    desk.import_vendors(VENDOR_CSV, "a")
    rid = desk.submit("a.txt", text_with(seller="RT Riyadh Branch", vat="300000000000003", po="none"), "text/plain", "r")
    run = desk.get_run(rid)
    assert run["status"] == "needs_review" and run["vendor_match"]["vendor"] is None
    vid = next(v["id"] for v in desk.list_vendors() if v["vat"] == "310000000000003")
    run = desk.link_vendor(rid, vid, "r")
    assert run["vendor_match"]["matched_on"] == "linked name" and run["status"] == "needs_review"   # the decision stays with a person
    known = next(x for x in run["results"] if x["key"] == "vendor-known")
    assert known["status"] == "pass"
    assert next(x for x in run["results"] if x["key"] == "vendor-vat")["status"] == "fail"           # its VAT still differs
    rid2 = desk.submit("b.txt", text_with(seller="RT Riyadh Branch", vat="310000000000003", po="none"), "text/plain", "r")
    assert desk.get_run(rid2)["status"] == "approved"                                               # next time it is known
    with pytest.raises(DeskError):
        desk.link_vendor(rid, 999, "r")


def test_vendor_rules_are_versioned_simulated_and_rolled_back(desk):
    desk.import_vendors(VENDOR_CSV, "a")
    desk.submit("a.txt", text_with(seller="Najd Office Supplies", vat="320000000000003", iban="", po="none"), "text/plain", "r")
    rule = next(r for r in desk.rules() if r["key"] == "vendor-blocked")
    before = desk.rules_version()
    sim = desk.simulate(rule=dict(rule, severity="review"))
    assert sim["changed_count"] >= 1
    desk.upsert_rule(dict(rule, severity="review"), "a")
    assert desk.rules_version() == before + 1
    desk.rollback(before, "a")
    assert next(r for r in desk.rules() if r["key"] == "vendor-blocked")["severity"] == "reject"


def test_seeded_desk_has_demo_vendors_and_reset_restores_them():
    d = Desk(":memory:", today=TODAY, sync=True, seed_vendors=True)
    n = len(d.list_vendors())
    assert n >= 5 and d.list_pos()
    d.save_vendor(dict(name_en="Extra"), "a")
    d.reset("a")
    assert len(d.list_vendors()) == n


def test_existing_database_keeps_its_rules(tmp_path):
    path = str(tmp_path / "x.db")
    d = Desk(path, today=TODAY, sync=True)
    d.db.run("DELETE FROM rules WHERE key LIKE 'vendor-%'")
    d2 = Desk(path, today=TODAY, sync=True, seed_vendors=True)
    assert not any(r["key"].startswith("vendor-") for r in d2.rules()) and not d2.list_vendors()


def test_csv_headers_are_forgiving():
    rows = read_csv("﻿VAT Number , Default Currency\n300000000000003,usd\n")
    assert rows == [{"vat": "300000000000003", "currency": "usd"}]


# ---- API ----------------------------------------------------------------------------------------------------
def test_api_roles_and_endpoints(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=1000))
    tok = lambda role: {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": role}).json()["token"]}  # noqa: E731
    v, r, a = tok("viewer"), tok("reviewer"), tok("admin")
    body = dict(name_en="Acme", vat="300000000000003", iban=IBAN_A)
    assert c.post("/api/vendors", json=body, headers=r).status_code == 403
    vid = c.post("/api/vendors", json=body, headers=a).json()["id"]
    assert c.post("/api/vendors", json=dict(name_en="X", iban="SA1"), headers=a).status_code == 400
    assert c.put(f"/api/vendors/{vid}", json=dict(body, status="blocked"), headers=a).json()["status"] == "blocked"
    assert c.get("/api/vendors", headers=v).json()[0]["name_en"] == "Acme"
    files = {"file": ("v.csv", VENDOR_CSV.encode("utf-8"), "text/csv")}
    assert c.post("/api/vendors/import", files=files, headers=a).json()["added"] == 2
    assert c.post("/api/vendors/import", files={"file": ("v.csv", b"\xff\xfe\x00", "text/csv")}, headers=a).status_code == 400
    assert c.post("/api/purchase-orders/import", files={"file": ("p.csv", PO_CSV.encode(), "text/csv")}, headers=a).json()["added"] == 2
    pid = c.get("/api/purchase-orders", headers=v).json()[0]["id"]
    rid = c.post("/api/runs", files={"files": ("a.txt", text_with(seller="Someone"), "text/plain")}, headers=r).json()["ids"][0]
    assert c.post(f"/api/runs/{rid}/link-vendor", json={"vendor_id": vid}, headers=v).status_code == 403
    assert c.post(f"/api/runs/{rid}/link-vendor", json={"vendor_id": vid}, headers=r).json()["vendor_match"]["vendor"]["id"] == vid
    assert c.post(f"/api/runs/{rid}/link-vendor", json={"vendor_id": "x"}, headers=r).status_code == 400
    assert c.delete(f"/api/purchase-orders/{pid}", headers=a).status_code == 200
    assert c.delete(f"/api/vendors/{vid}", headers=a).status_code == 200
    assert c.delete(f"/api/vendors/{vid}", headers=a).status_code == 404
