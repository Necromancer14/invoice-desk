from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
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


# The welcome set for a first visit: samples the built-in reader reads as the answer key expects, so the dashboard shows
# 11 approved, 6 sent to review and 3 rejected across text, PDF and XML, English and Arabic. No duplicates, no images.
DEMO_SET = ["inv-003.txt", "inv-004.pdf", "inv-016.pdf", "inv-017.pdf", "inv-022.pdf", "inv-035.pdf", "inv-061.txt", "inv-062.txt",
            "inv-063.txt", "inv-064.txt", "inv-067.txt", "inv-071.pdf", "inv-074.xml", "inv-091.pdf", "inv-092.pdf", "inv-078.xml",
            "inv-081.xml", "inv-082.txt", "inv-090.pdf", "inv-089.txt"]


# Scenarios a demo reviewer turns down when one of the history invoices lands in review; the rest are approved.
REJECT_SCENARIOS = {"bad_vat", "vat_rate", "totals", "qr_mismatch", "missing_vat", "due_before_issue", "prompt_injection",
                    "zero_rated_wrong", "iban_changed", "blocked_vendor", "vendor_vat_mismatch", "po_over", "future_date",
                    "hijri_future", "unknown_vendor"}
# Made-up reviewers who decide the history invoices that went to review.
DEMO_REVIEWERS = ("noura", "faisal")
HISTORY_DAYS = 30


def history_set(root: Path = SAMPLES) -> list[dict]:
    """Samples for the demo's past 30 days: every one the built-in reader can read that is not in the welcome set, not a
    planned duplicate and not the original of a PDF copy in the welcome set (either would turn a welcome invoice into a
    duplicate)."""
    items = load_answers(root)["invoices"]
    copied = {i["copy_of"] for i in items if i["file"] in DEMO_SET and i.get("copy_of")}
    return [i for i in items if i["file"] not in DEMO_SET and not i["vision_only"] and i["scenario"] != "duplicate"
            and i["id"] not in copied]


def demo_plan(end: datetime, now: datetime, history: bool = True, seed: int = 7, root: Path = SAMPLES) -> list[dict]:
    """The demo load in date order: history spread over days 8 to 29 before `end`, then the welcome set over the last 7
    days with the invoices that go to review in the last 2. Each item: file, at (UTC), and for history a decision a
    demo reviewer takes if the invoice lands in review (an invoice the reader could not read is never approved).
    Nothing is later than `now`."""
    rng = random.Random(seed)
    answers = {i["file"]: i for i in load_answers(root)["invoices"]}
    midnight = datetime.combine(end.date(), datetime.min.time(), tzinfo=timezone.utc)

    def at(days_back: int) -> datetime:
        # working hours in Riyadh, 08:00 to 17:00 (05:00 to 14:00 UTC)
        t = midnight - timedelta(days=days_back) + timedelta(hours=5, minutes=rng.randint(0, 9 * 60))
        return min(t, now - timedelta(minutes=rng.randint(5, 90)))

    plan: list[dict] = []
    if history:
        hist = history_set(root)
        rng.shuffle(hist)
        first = HISTORY_DAYS - 1  # day 29 before today is the first day of a 30-day window that ends today
        for n, item in enumerate(hist):
            back = first - round(n * (first - 8) / max(1, len(hist) - 1))
            reject = item["scenario"] in REJECT_SCENARIOS
            plan.append(dict(file=item["file"], at=at(back), decide=dict(
                decision="reject" if reject else "approve", actor=DEMO_REVIEWERS[n % 2],
                note=f"Rejected: {LABELS.get(item['scenario'], item['scenario'])}" if reject else "",
                unreadable_note="Rejected: could not be read. Asked the vendor for a clearer copy.",
                after=timedelta(minutes=rng.randint(20, 26 * 60)))))
    for name in DEMO_SET:
        waits = answers[name]["expected_status"] == "needs_review"
        plan.append(dict(file=name, at=at(rng.randint(0, 1) if waits else rng.randint(0, 6)), decide=None))
    plan.sort(key=lambda p: p["at"])
    return plan


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
