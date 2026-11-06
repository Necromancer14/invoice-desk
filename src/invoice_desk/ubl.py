"""UBL 2.1 XML invoices, the format ZATCA e-invoicing uses, read directly into the desk's fields. No AI is needed.

Only the fields the rules check are read. Signatures, the hash chain, certificates and the cryptographic stamp are
not checked here.

Safety: any DOCTYPE or ENTITY declaration is refused before parsing, so there are no external entities and no entity
expansion; a UBL invoice never needs either.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

from .extractors import Extraction, _overall
from .schema import REQUIRED, SCALARS, empty_fields
from .textnorm import parse_date, to_number

NS = {
    "inv": "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
    "cac": "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2",
    "cbc": "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2",
}
_UNSAFE = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


class XmlError(ValueError):
    """The upload is not a UBL invoice this reader can accept. The message says why, in plain words."""


def check_safe(blob: bytes) -> None:
    if _UNSAFE.search(blob):
        raise XmlError("XML with a DOCTYPE or ENTITY declaration is not accepted")


def looks_like_xml(blob: bytes) -> bool:
    head = blob[:2048].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head.startswith(b"<?xml") or head.startswith(b"<")


def _text(node, path: str) -> str | None:
    found = node.find(path, NS) if node is not None else None
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _party(root, which: str) -> tuple[str | None, str | None]:
    party = root.find(f"cac:{which}/cac:Party", NS)
    name = _text(party, "cac:PartyLegalEntity/cbc:RegistrationName") or _text(party, "cac:PartyName/cbc:Name")
    vat = _text(party, "cac:PartyTaxScheme/cbc:CompanyID")
    return name, (re.sub(r"\s", "", vat) if vat else None)


def read(blob: bytes) -> dict:
    """The desk's fields from a UBL 2.1 invoice. Raises XmlError for unsafe, malformed or non-invoice XML."""
    check_safe(blob)
    try:
        root = ET.fromstring(blob)
    except ET.ParseError as exc:
        raise XmlError(f"the XML could not be read ({exc})") from None
    if root.tag != f"{{{NS['inv']}}}Invoice":
        raise XmlError("this XML is not a UBL 2.1 Invoice")
    f = empty_fields()
    f["invoice_number"] = _text(root, "cbc:ID")
    f["issue_date"] = parse_date(_text(root, "cbc:IssueDate"))
    f["due_date"] = parse_date(_text(root, "cbc:DueDate") or _text(root, "cac:PaymentMeans/cbc:PaymentDueDate"))
    type_name = (root.find("cbc:InvoiceTypeCode", NS).get("name", "") if root.find("cbc:InvoiceTypeCode", NS) is not None else "")
    f["invoice_type"] = {"01": "standard", "02": "simplified"}.get(type_name[:2])
    f["currency"] = (_text(root, "cbc:DocumentCurrencyCode") or "").upper() or None
    f["seller_name"], f["seller_vat"] = _party(root, "AccountingSupplierParty")
    f["buyer_name"], f["buyer_vat"] = _party(root, "AccountingCustomerParty")
    f["subtotal"] = to_number(_text(root, "cac:LegalMonetaryTotal/cbc:TaxExclusiveAmount"))
    f["total"] = to_number(_text(root, "cac:LegalMonetaryTotal/cbc:TaxInclusiveAmount") or _text(root, "cac:LegalMonetaryTotal/cbc:PayableAmount"))
    # ZATCA invoices carry two TaxTotal elements; the one in the document currency is the VAT amount
    totals = root.findall("cac:TaxTotal/cbc:TaxAmount", NS)
    pick = next((t for t in totals if t.get("currencyID", "").upper() == (f["currency"] or "")), totals[0] if totals else None)
    f["vat_amount"] = to_number(pick.text) if pick is not None else None
    iban = _text(root, "cac:PaymentMeans/cac:PayeeFinancialAccount/cbc:ID")
    f["iban"] = re.sub(r"\s", "", iban).upper() if iban else None
    f["po_number"] = _text(root, "cac:OrderReference/cbc:ID")
    for ref in root.findall("cac:AdditionalDocumentReference", NS):
        if (_text(ref, "cbc:ID") or "").upper() == "QR":
            f["qr_payload"] = re.sub(r"\s", "", _text(ref, "cac:Attachment/cbc:EmbeddedDocumentBinaryObject") or "") or None
    for line in root.findall("cac:InvoiceLine", NS):
        item = dict(description=_text(line, "cac:Item/cbc:Name") or "", quantity=to_number(_text(line, "cbc:InvoicedQuantity")),
                    unit_price=to_number(_text(line, "cac:Price/cbc:PriceAmount")), line_total=to_number(_text(line, "cbc:LineExtensionAmount")))
        category = (_text(line, "cac:Item/cac:ClassifiedTaxCategory/cbc:ID") or "").upper()[:1]
        if category in ("S", "Z", "E", "O"):
            item["vat_category"] = category
        f["line_items"].append(item)
    return f


class UblExtractor:
    """Reads UBL XML. Used for every XML upload, whatever reading mode was chosen."""
    name = "ubl-xml"

    def extract(self, blob: bytes, content_type: str, filename: str = "") -> Extraction:
        t0 = time.time()
        fields = read(blob)
        fc = {k: (1.0 if fields.get(k) not in (None, "") else 0.0) for k in SCALARS}
        notes = [f"could not find {k}" for k in REQUIRED if fields.get(k) in (None, "")]
        return Extraction(fields, _overall(fields, fc), fc, notes, self.name, None, 0, 0, int((time.time() - t0) * 1000))


def write(f: dict, uuid: str = "00000000-0000-0000-0000-000000000000", issue_time: str = "09:30:00") -> str:
    """A small UBL 2.1 invoice from the desk's fields. Used for the tests and the sample set, not for submission."""
    cur = f.get("currency") or "SAR"
    amt = lambda v: f"{float(v):.2f}"  # noqa: E731
    el = lambda tag, value, **attrs: (f"<{tag}" + "".join(f" {k}={quoteattr(str(v))}" for k, v in attrs.items())  # noqa: E731
                                      + f">{escape(str(value))}</{tag}>") if value not in (None, "") else ""

    def party(which, name, vat):
        return (f"<cac:{which}><cac:Party>"
                + (f"<cac:PartyTaxScheme>{el('cbc:CompanyID', vat)}<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>" if vat else "")
                + f"<cac:PartyLegalEntity>{el('cbc:RegistrationName', name)}</cac:PartyLegalEntity></cac:Party></cac:{which}>")
    lines = []
    for n, i in enumerate(f.get("line_items") or [], 1):
        cat = i.get("vat_category") or "S"
        lines.append(f"<cac:InvoiceLine>{el('cbc:ID', n)}{el('cbc:InvoicedQuantity', i.get('quantity'), unitCode='PCE')}"
                     f"{el('cbc:LineExtensionAmount', amt(i['line_total']), currencyID=cur)}<cac:Item>{el('cbc:Name', i.get('description'))}"
                     f"<cac:ClassifiedTaxCategory>{el('cbc:ID', cat)}{el('cbc:Percent', '15' if cat == 'S' else '0')}"
                     f"<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>"
                     f"<cac:Price>{el('cbc:PriceAmount', amt(i['unit_price']), currencyID=cur)}</cac:Price></cac:InvoiceLine>")
    qr = (f"<cac:AdditionalDocumentReference><cbc:ID>QR</cbc:ID><cac:Attachment>"
          f"{el('cbc:EmbeddedDocumentBinaryObject', f['qr_payload'], mimeCode='text/plain')}</cac:Attachment></cac:AdditionalDocumentReference>"
          if f.get("qr_payload") else "")
    type_name = "0200000" if f.get("invoice_type") == "simplified" else "0100000"
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<Invoice xmlns="{NS["inv"]}" xmlns:cac="{NS["cac"]}" xmlns:cbc="{NS["cbc"]}">'
            f"<cbc:ProfileID>reporting:1.0</cbc:ProfileID>{el('cbc:ID', f.get('invoice_number'))}{el('cbc:UUID', uuid)}"
            f"{el('cbc:IssueDate', f.get('issue_date'))}{el('cbc:IssueTime', issue_time)}{el('cbc:DueDate', f.get('due_date'))}"
            f"{el('cbc:InvoiceTypeCode', '388', name=type_name)}{el('cbc:DocumentCurrencyCode', cur)}{el('cbc:TaxCurrencyCode', 'SAR')}"
            f"{'<cac:OrderReference>' + el('cbc:ID', f['po_number']) + '</cac:OrderReference>' if f.get('po_number') else ''}{qr}"
            f"{party('AccountingSupplierParty', f.get('seller_name'), f.get('seller_vat'))}"
            f"{party('AccountingCustomerParty', f.get('buyer_name'), f.get('buyer_vat'))}"
            f"{'<cac:PaymentMeans><cbc:PaymentMeansCode>30</cbc:PaymentMeansCode><cac:PayeeFinancialAccount>' + el('cbc:ID', f['iban']) + '</cac:PayeeFinancialAccount></cac:PaymentMeans>' if f.get('iban') else ''}"
            f"<cac:TaxTotal>{el('cbc:TaxAmount', amt(f['vat_amount']), currencyID=cur)}</cac:TaxTotal>"
            f"<cac:LegalMonetaryTotal>{el('cbc:LineExtensionAmount', amt(f['subtotal']), currencyID=cur)}"
            f"{el('cbc:TaxExclusiveAmount', amt(f['subtotal']), currencyID=cur)}{el('cbc:TaxInclusiveAmount', amt(f['total']), currencyID=cur)}"
            f"{el('cbc:PayableAmount', amt(f['total']), currencyID=cur)}</cac:LegalMonetaryTotal>{''.join(lines)}</Invoice>\n")
