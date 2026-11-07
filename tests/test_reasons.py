"""The portal shows check reasons and vendor match explanations in Arabic by matching them against the templates in
web/src/reasons.ts. These tests make the server's sentences and those templates stay in step: every reason the
rules, the vendor matcher and the purchase order check can write must be covered, and every template must still be
one the server writes."""
import json
import re
from datetime import date
from pathlib import Path

import pytest

from invoice_desk import evaluation
from invoice_desk.default_rules import DEFAULT_RULES
from invoice_desk.qr import encode
from invoice_desk.rules import Ctx, run_rules
from invoice_desk.extractors import guess_type
from invoice_desk.vendors import VendorBook, iban_problem, po_match, saudi_iban
from conftest import TODAY

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "web" / "src" / "reasons.ts").read_text(encoding="utf-8")
AR = json.loads((ROOT / "web" / "src" / "locales" / "ar.json").read_text(encoding="utf-8"))


def _list(name: str) -> list[str]:
    body = re.search(rf"export const {name} = \[(.*?)\n\];", SOURCE, re.S).group(1)
    return [json.loads(f'"{m}"') for m in re.findall(r'(?<![\w.$])tk\("((?:[^"\\\n]|\\.)*)"\)', body)]


REASONS, MESSAGES = _list("REASONS"), _list("MESSAGES")
FIELD = "[a-z_]+"
GROUP = {"field": f"({FIELD})", "fields": f"({FIELD}(?:, {FIELD})*)", "what": "(English name|Arabic name|linked name|VAT number)"}


def _compile(tpl: str):
    names, out = [], []
    for part in re.split(r"(\{\w+\})", tpl):
        m = re.fullmatch(r"\{(\w+)\}", part)
        if m:
            names.append(m.group(1))
            out.append(GROUP.get(m.group(1), r"((?:(?!; ).)+?)"))
        else:
            out.append(re.escape(part))
    return tpl, names, re.compile("".join(out))


COMPILED = [_compile(t) for t in REASONS]


def covered(text: str, used: set) -> bool:
    """The same steps as translate() in reasons.ts: a template, a rule message around a detail, or "; " parts."""
    for tpl, names, rx in COMPILED:
        m = rx.fullmatch(text)
        if m:
            used.add(tpl)
            if "problem" in names:
                covered(m.group(names.index("problem") + 1), used)
            return True
    w = re.fullmatch(r"(.+?) \((.*)\)", text)
    if w and w.group(1) in MESSAGES and covered(w.group(2), used):
        return True
    return "; " in text and all(covered(p, used) for p in text.split("; "))


# ---- every sentence the server can write ------------------------------------------------------------
IBAN_A, IBAN_B = saudi_iban("80", "000123456789012345"), saudi_iban("10", "000000000000000777")
RAJHI = dict(id=1, name_en="Al Rajhi Trading Co.", name_ar="شركة الراجحي للتجارة", vat="310000000000003", iban=IBAN_A,
             currency="SAR", status="approved")
NAJD = dict(id=2, name_en="Najd Office Supplies", name_ar=None, vat="320000000000003", iban=None, currency="SAR", status="blocked")
BOOK = VendorBook([RAJHI, NAJD], [dict(vendor_id=1, alias="Rajhi Co")])
POS = {"PO-100": dict(po_number="PO-100", vendor_id=1, vendor_name="Al Rajhi Trading Co.", amount=1150.0, currency="SAR", status="open"),
       "PO-200": dict(po_number="PO-200", vendor_id=2, vendor_name="Najd Office Supplies", amount=50.0, currency="USD", status="closed")}
BASE = dict(invoice_number="A-1", issue_date="2026-10-01", due_date="2026-11-01", seller_name="Al Rajhi Trading Co.",
            seller_vat="310000000000003", buyer_name="B", buyer_vat=None, currency="SAR", subtotal=1000.0, vat_amount=150.0,
            total=1150.0, qr_payload=None, iban=IBAN_A, po_number="PO-100", invoice_type="standard",
            line_items=[dict(description="x", quantity=2, unit_price=500.0, line_total=1000.0, vat_category="S")])
QR = encode("Other Seller", "300000000000003", "2026-09-01T10:00:00Z", 999.0, 99.0)
EXTRA_RULES = [
    dict(key="re", name="re", type="regex", severity="review", params={"field": "invoice_number", "pattern": r"[0-9]+"}),
    dict(key="re_bad", name="re_bad", type="regex", severity="review", params={"field": "invoice_number", "pattern": "("}),
    dict(key="re_po", name="re_po", type="regex", severity="review", params={"field": "po_number", "pattern": ".+"}),
    dict(key="old", name="old", type="date_valid", severity="review", params={"field": "due_date", "max_age_days": 3}),
    dict(key="min", name="min", type="amount_limit", severity="review", params={"field": "subtotal", "min": 5000, "max": None}),
    dict(key="qr_req", name="qr_req", type="qr_match", severity="review", params={"required": True}),
    dict(key="qr_simpl", name="qr_simpl", type="qr_present", severity="review", params={"simplified_only": True}),
    dict(key="ex", name="ex", type="expression", severity="review", params={"expr": "total < 100"}),
    dict(key="ex_none", name="ex_none", type="expression", severity="review", params={"expr": "buyer_vat > 1"}),
]
RULES = [dict(r, enabled=True) for r in DEFAULT_RULES] + [dict(r, enabled=True, message="") for r in EXTRA_RULES]
VARIANTS = [
    {}, dict(seller_vat="12345"), dict(seller_vat=None), dict(buyer_vat="999"), dict(vat_amount=10.0, total=1010.0),
    dict(vat_amount=None), dict(subtotal=None), dict(total=2000.0), dict(subtotal=900.0, total=1035.0, vat_amount=135.0),
    dict(line_items=[dict(description="x", quantity=3, unit_price=500.0, line_total=1000.0)]), dict(line_items=[]),
    dict(line_items=[dict(description="s", quantity=1, unit_price=None, line_total=None, vat_category="S"),
                     dict(description="z", quantity=1, unit_price=100.0, line_total=100.0, vat_category="Z")]),
    dict(line_items=[dict(description="s", quantity=1, unit_price=800.0, line_total=800.0, vat_category="S"),
                     dict(description="z", quantity=1, unit_price=200.0, line_total=200.0, vat_category="Z")]),
    dict(issue_date="2027-01-01"), dict(issue_date="yesterday"), dict(issue_date=None), dict(due_date="2026-09-01"),
    dict(due_date=None), dict(currency="USD"), dict(currency=None), dict(total=90000.0, subtotal=None), dict(total=-5.0, subtotal=None),
    dict(total=None), dict(qr_payload="not base64!"), dict(qr_payload=QR), dict(seller_name="Unknown Shop", seller_vat="300000000000003"),
    dict(seller_name="Totally Different", seller_vat=None), dict(seller_name=None, seller_vat=None),
    dict(seller_name="Zzz", seller_vat="310000000000003"), dict(seller_name="Al Rajhi Trading"), dict(seller_name="Rajhi Co"),
    dict(seller_name="Najd Office Supplies", seller_vat="320000000000003", po_number="PO-200", currency="USD", iban=IBAN_B),
    dict(seller_name="Najd Office Supplies", seller_vat="320000000000003", po_number="PO-200", currency="SAR", total=10.0, subtotal=None),
    dict(seller_vat="310000000000013"), dict(iban=None), dict(iban=IBAN_B), dict(iban="SA00"), dict(iban="SA0380000000608010167518"),
    dict(iban="XX"), dict(iban="SA03800000006080101675199"), dict(po_number=None), dict(po_number="PO-999"),
    dict(po_number="PO-200"), dict(total=1500.0, subtotal=None), dict(invoice_number=None), dict(buyer_vat=None, invoice_type="simplified"),
]


def _server_reasons() -> list[str]:
    out = []
    for book in (BOOK, VendorBook([])):
        for dup in (False, True):
            for conf in (1.0, 0.5):
                ctx = Ctx(today=TODAY, confidence=conf, is_duplicate=lambda v, n, d=dup: d, vendors=book, po_for=POS.get)
                for over in VARIANTS:
                    fields = dict(BASE, **over)
                    out += [r["detail"] for r in run_rules(RULES, fields, ctx) if r["status"] != "pass"]
                    if book:
                        out.append(book.match(fields)["why"])
    for value in ("", "hello", "SA12", "SA0380000000608010167518"):
        out.append(iban_problem(value) or "")
    for fields, po, vendor in ((dict(BASE, po_number=None), None, RAJHI), (BASE, None, RAJHI), (BASE, POS["PO-200"], RAJHI),
                               (dict(BASE, po_number="PO-200"), POS["PO-200"], NAJD), (dict(BASE, total=10.0), POS["PO-200"], None)):
        out.append(po_match(fields, po, vendor)["detail"])
    out.append(po_match(BASE, POS["PO-100"], RAJHI)["detail"])
    out.append(po_match(dict(BASE, currency="USD", total=10.0), POS["PO-200"], NAJD)["detail"])
    out.append(BOOK.match(dict(BASE, seller_name="Al Rajhi Trading Riyadh"), 0.5)["why"])
    return [x for x in out if x]


@pytest.fixture(scope="module")
def sample_reasons() -> list[str]:
    """Every reason the bundled samples produce through the normal pipeline, with the demo vendor master."""
    data = evaluation.load_answers()
    desk = evaluation._desk(data, None)
    out = []
    for it in data["invoices"]:
        blob = (evaluation.SAMPLES / it["file"]).read_bytes()
        run = desk.get_run(desk.submit(it["file"], blob, guess_type(it["file"], None), "test", source="evaluation"))
        out += [r["detail"] for r in run["results"] if r["status"] != "pass" and r["detail"]]
        if run.get("vendor_match"):
            out.append(run["vendor_match"]["why"])
    return out


def test_templates_parse_and_have_arabic():
    assert len(REASONS) > 50 and len(MESSAGES) == len({r["message"] for r in DEFAULT_RULES if r["message"]})
    assert {r["message"] for r in DEFAULT_RULES if r["message"]} == set(MESSAGES)
    for tpl in REASONS + MESSAGES:
        assert tpl in AR, tpl
        assert set(re.findall(r"\{\w+\}", tpl)) == set(re.findall(r"\{\w+\}", AR[tpl])), tpl
        assert chr(0x2014) not in AR[tpl]  # no em dashes


def test_every_reason_the_rules_write_is_covered():
    missing = sorted({x for x in _server_reasons() if not covered(x, set())})
    assert not missing, "no template in web/src/reasons.ts for:\n" + "\n".join(missing)


def test_every_reason_the_samples_produce_is_covered(sample_reasons):
    assert sample_reasons
    missing = sorted({x for x in sample_reasons if not covered(x, set())})
    assert not missing, "no template in web/src/reasons.ts for:\n" + "\n".join(missing)


def test_every_template_is_still_one_the_server_writes(sample_reasons):
    used: set = set()
    for x in _server_reasons() + sample_reasons:
        covered(x, used)
    assert not set(REASONS) - used, f"templates the server no longer writes: {sorted(set(REASONS) - used)}"


def test_specific_templates_win_over_general_ones():
    used: set = set()
    covered("VAT is 140.00 but 15% of the standard-rated 800.00 is 120.00 (zero-rated and exempt lines carry no VAT)", used)
    assert used == {"VAT is {vat} but {rate}% of the standard-rated {taxable} is {expected} (zero-rated and exempt lines carry no VAT)"}
    used.clear()
    covered("it is empty", used)
    assert used == {"it is empty"}
    used.clear()
    covered("QR VAT 300000000000003 vs printed 310000000000003; QR total 999.00 vs printed 1150.00", used)
    assert used == {"QR VAT {qr} vs printed {printed}", "QR {field} {qr} vs printed {printed}"}
    used.clear()
    covered("currency missing", used)
    assert used == {"currency missing"}
    assert not covered("Something an admin typed", set())
