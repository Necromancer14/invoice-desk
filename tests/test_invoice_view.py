"""The readable invoice view of a UBL XML run: ubl.view() and GET /api/runs/{id}/invoice."""
import pytest
from fastapi.testclient import TestClient

from invoice_desk import qr, ubl
from invoice_desk.api import create_app
from invoice_desk.desk import Desk
from invoice_desk.samples import sample_bytes
from conftest import GOOD, TODAY

FIELDS = dict(invoice_number="GHC-2026-0001", issue_date="2026-10-01", due_date="2026-11-01", invoice_type="standard",
              seller_name="Gulf Horizon Consulting", seller_vat="300000000000003", buyer_name="شركة المشتري", buyer_vat="311111111111113",
              currency="SAR", subtotal=1500.0, vat_amount=150.0, total=1650.0, iban="SA0380000000608010167519", po_number="PO-2026-0001",
              line_items=[dict(description="Consulting", quantity=2, unit_price=500.0, line_total=1000.0),
                          dict(description="Export freight", quantity=1, unit_price=500.0, line_total=500.0, vat_category="Z")],
              qr_payload=qr.encode("Gulf Horizon Consulting", "300000000000003", "2026-10-01T09:30:00Z", 1650.0, 150.0))

ADDRESS = ("<cac:PostalAddress><cbc:StreetName>King Fahd Road</cbc:StreetName><cbc:BuildingNumber>1234</cbc:BuildingNumber>"
           "<cbc:CitySubdivisionName>Al Olaya</cbc:CitySubdivisionName><cbc:CityName>Riyadh</cbc:CityName>"
           "<cbc:PostalZone>12211</cbc:PostalZone><cac:Country><cbc:IdentificationCode>SA</cbc:IdentificationCode></cac:Country>"
           "</cac:PostalAddress>")


def xml(**over) -> bytes:
    return ubl.write(dict(FIELDS, **over), issue_time="09:30:00").encode()


def test_view_has_what_a_reviewer_reads():
    v = ubl.view(xml())
    assert (v["invoice_number"], v["issue_date"], v["issue_time"], v["due_date"], v["currency"], v["invoice_type"]) == \
        ("GHC-2026-0001", "2026-10-01", "09:30:00", "2026-11-01", "SAR", "standard")
    assert v["seller"] == {"name": "Gulf Horizon Consulting", "vat": "300000000000003", "address": []}
    assert v["buyer"]["name"] == "شركة المشتري" and v["buyer"]["vat"] == "311111111111113"
    assert (v["subtotal"], v["vat_amount"], v["total"]) == (1500.0, 150.0, 1650.0)
    assert v["iban"] == "SA0380000000608010167519" and v["po_number"] == "PO-2026-0001"
    assert v["qr_payload"] == FIELDS["qr_payload"]


def test_view_lines_carry_vat_category_and_rate():
    lines = ubl.view(xml())["lines"]
    assert [(i["description"], i["quantity"], i["unit_price"], i["line_total"]) for i in lines] == \
        [("Consulting", 2, 500.0, 1000.0), ("Export freight", 1, 500.0, 500.0)]
    assert [(i["vat_category"], i["vat_rate"]) for i in lines] == [("S", 15), ("Z", 0)]


def test_view_reads_postal_address_into_lines():
    blob = xml().decode().replace("<cac:PartyTaxScheme>", ADDRESS + "<cac:PartyTaxScheme>", 1).encode()
    seller = ubl.view(blob)["seller"]
    assert seller["address"] == ["King Fahd Road 1234", "Al Olaya, Riyadh", "12211 SA"]
    assert ubl.view(blob)["buyer"]["address"] == []


def test_view_without_optional_parts():
    v = ubl.view(xml(iban=None, po_number=None, qr_payload=None, buyer_vat=None, due_date=None))
    assert v["iban"] is None and v["po_number"] is None and v["qr_payload"] is None and v["due_date"] is None
    assert v["buyer"]["vat"] is None


@pytest.mark.parametrize("blob, why", [
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Invoice>&e;</Invoice>', "DOCTYPE or ENTITY"),
    (b"<Invoice><broken></Invoice>", "could not be read"),
    (b"<Order xmlns='x'/>", "not a UBL 2.1 Invoice"),
])
def test_view_refuses_what_read_refuses(blob, why):
    with pytest.raises(ubl.XmlError, match=why):
        ubl.view(blob)


def test_view_of_every_bundled_xml_sample():
    from invoice_desk.samples import list_samples
    names = [s["file"] for s in list_samples() if s["file"].endswith(".xml")]
    assert names
    for n in names:
        v = ubl.view(sample_bytes(n))
        assert v["invoice_number"] and v["seller"]["name"] and v["lines"] and v["total"] is not None, n


@pytest.fixture
def client(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=1000))
    hdr = lambda role: {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": role}).json()["token"]}  # noqa: E731
    return c, hdr


def test_endpoint_returns_the_view_to_a_viewer(client):
    c, hdr = client
    rid = c.post("/api/runs", files={"files": ("inv.xml", xml(), "application/xml")}, headers=hdr("reviewer")).json()["ids"][0]
    r = c.get(f"/api/runs/{rid}/invoice", headers=hdr("viewer"))
    assert r.status_code == 200
    body = r.json()
    assert body["invoice_number"] == "GHC-2026-0001" and len(body["lines"]) == 2 and body["iban"] == FIELDS["iban"]
    assert c.get(f"/api/runs/{rid}/invoice").status_code == 401


def test_endpoint_is_404_for_other_files_and_missing_runs(client):
    c, hdr = client
    h = hdr("reviewer")
    rid = c.post("/api/runs", files={"files": ("a.txt", GOOD, "text/plain")}, headers=h).json()["ids"][0]
    assert c.get(f"/api/runs/{rid}/invoice", headers=h).status_code == 404
    assert c.get("/api/runs/99999/invoice", headers=h).status_code == 404


def test_endpoint_is_422_for_unreadable_xml(client):
    c, hdr = client
    h = hdr("reviewer")
    rid = c.post("/api/runs", files={"files": ("x.xml", b"<Invoice><broken></Invoice>", "application/xml")}, headers=h).json()["ids"][0]
    r = c.get(f"/api/runs/{rid}/invoice", headers=h)
    assert r.status_code == 422 and "could not be read" in r.json()["detail"]
