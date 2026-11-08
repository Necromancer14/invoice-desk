"""The PDF copies of three XML demo samples (changed IBAN, wrong VAT number, QR code mismatch): the built-in reader
reads them to the same fields and the same decision as the XML they were made from."""
import pytest

from invoice_desk.desk import Desk
from invoice_desk.samples import DEMO_SET, load_answers, sample_bytes
from conftest import TODAY

ANSWERS = {i["id"]: i for i in load_answers()["invoices"]}
COPIES = [i for i in ANSWERS.values() if i.get("copy_of")]


def test_three_copies_of_the_demo_xml_samples():
    assert [(c["id"], c["copy_of"], c["scenario"]) for c in COPIES] == [
        ("inv-090", "inv-084", "iban_changed"), ("inv-091", "inv-075", "bad_vat"), ("inv-092", "inv-077", "qr_mismatch")]
    for c in COPIES:
        src = ANSWERS[c["copy_of"]]
        assert c["format"] == "pdf" and src["format"] == "xml" and c["expected_status"] == src["expected_status"]
        # the same invoice apart from its number, so loading both is not a duplicate
        assert {k: v for k, v in c["truth"].items() if k != "invoice_number"} == {k: v for k, v in src["truth"].items() if k != "invoice_number"}
        assert c["truth"]["invoice_number"] != src["truth"]["invoice_number"]


@pytest.mark.parametrize("copy", COPIES, ids=lambda c: c["id"])
def test_copy_reads_to_the_same_fields_and_decision(copy):
    d = Desk(":memory:", today=TODAY, sync=True, seed_vendors=True)
    rid = d.submit(copy["file"], sample_bytes(copy["file"]), "application/pdf", "r")
    run = d.get_run(rid)
    assert run["status"] == copy["expected_status"], [r for r in run["results"] if r["status"] == "fail"]
    f, truth = run["extracted"], copy["truth"]
    for k in ("invoice_number", "seller_vat", "total", "vat_amount", "iban", "po_number", "qr_payload"):
        assert f.get(k) == truth.get(k), k
    src = ANSWERS[copy["copy_of"]]
    xml = d.get_run(d.submit(src["file"], sample_bytes(src["file"]), "application/xml", "r"))
    assert xml["status"] == run["status"]
    failed = lambda r: sorted(x["key"] for x in r["results"] if x["status"] == "fail")  # noqa: E731
    assert failed(xml) == failed(run)


def test_welcome_set_shows_the_pdf_copies_not_their_xml():
    assert {"inv-090.pdf", "inv-091.pdf", "inv-092.pdf"} <= set(DEMO_SET)
    assert not {"inv-075.xml", "inv-077.xml", "inv-084.xml"} & set(DEMO_SET)
