from __future__ import annotations

from pathlib import Path

from .evaluation import SAMPLES, load_answers

LABELS = {"clean": "Clean invoice", "prompt_injection": "Hidden instruction inside the invoice", "bad_vat": "Malformed seller VAT number",
          "vat_rate": "Wrong VAT rate", "totals": "Totals do not add up", "future_date": "Issue date in the future",
          "duplicate": "Duplicate of an earlier invoice", "qr_mismatch": "QR code disagrees with printed total",
          "non_sar": "Foreign currency", "over_limit": "High value invoice", "missing_vat": "Seller VAT number missing",
          "due_before_issue": "Due date before issue date",
          # checks against ZATCA e-invoicing fields
          "vat_digits_spaced": "VAT number in Arabic digits, grouped with spaces",
          "arabic_decimals": "Arabic-Indic digits and decimal separators",
          "zero_rated": "Zero-rated line, VAT on the rest only",
          "exempt": "Exempt line, VAT on the rest only",
          "zero_rated_wrong": "VAT charged on a zero-rated line",
          "hijri_date": "Hijri issue date",
          "hijri_future": "Hijri issue date in the future",
          "qr_missing": "No QR code on the invoice",
          "simplified": "Simplified tax invoice",
          # vendor master and purchase orders
          "vendor_ok": "Known vendor, IBAN and PO agree", "vendor_fuzzy": "Vendor name written differently",
          "iban_changed": "IBAN differs from the vendor master", "blocked_vendor": "Blocked vendor",
          "unknown_vendor": "Vendor not in the vendor master", "vendor_vat_mismatch": "VAT number differs from the vendor master",
          "po_over": "Invoice above its purchase order"}


def list_samples(root: Path = SAMPLES) -> list[dict]:
    out = []
    for it in load_answers(root)["invoices"]:
        out.append(dict(id=it["id"], file=it["file"], format=it["format"], lang=it["lang"], scenario=it["scenario"],
                        label=LABELS.get(it["scenario"], it["scenario"]), vision_only=it["vision_only"]))
    return out


def sample_bytes(file: str, root: Path = SAMPLES) -> bytes:
    p = (root / file).resolve()
    if root.resolve() not in p.parents or not p.is_file():
        raise FileNotFoundError(file)
    return p.read_bytes()
