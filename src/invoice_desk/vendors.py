"""Vendor master and purchase orders: validation, name matching and PO lookup. Deterministic and explainable; no AI.

Matching normalises a name (case, spacing, punctuation, Arabic diacritics and letter variants, digits, the article and
legal words such as LLC or شركة), then compares it with each vendor's English name, Arabic name and linked names.
An exact match after normalising scores 1.0; otherwise 0.6 x token overlap + 0.4 x character similarity. English and
Arabic names meet through the vendor record, which holds both; nothing is transliterated.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from difflib import SequenceMatcher

from .textnorm import normalize, to_number, vat_key

DEFAULT_MIN_SCORE = 0.85
STATUSES = ("approved", "blocked")
PO_STATUSES = ("open", "closed")

# ---- names --------------------------------------------------------------------------------------
_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
_LETTERS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي", "ـ": ""})
_PUNCT = re.compile(r"[^\w\s]|_", re.U)
# legal forms and filler words, compared after normalising (so ة is already ه and ؤ is و)
LEGAL_WORDS = {
    "llc", "ltd", "limited", "co", "company", "corp", "corporation", "inc", "est", "establishment", "the", "and", "of", "for",
    "al", "el", "plc", "lc", "sa", "wll",
    "شركه", "موسسه", "محدوده", "ذات", "مسوليه", "مسووليه", "ذمم", "مساهمه", "و",
}
_AR_PREFIXES = ("وال", "بال", "لل", "ال")


def _is_arabic(token: str) -> bool:
    return any("؀" <= c <= "ۿ" for c in token)


def name_tokens(name: str | None) -> list[str]:
    """The words of a name that matter for matching, in order."""
    text = unicodedata.normalize("NFKC", normalize(str(name or ""))).casefold()
    text = _DIACRITICS.sub("", text).translate(_LETTERS)
    text = _PUNCT.sub(" ", text.replace("&", " and "))
    out = []
    for tok in text.split():
        if _is_arabic(tok):
            for pre in _AR_PREFIXES:
                if tok.startswith(pre) and len(tok) - len(pre) >= 2:
                    tok = tok[len(pre):]
                    break
            if len(tok) < 2:
                continue
        if tok not in LEGAL_WORDS:
            out.append(tok)
    return out


def name_key(name: str | None) -> str:
    return " ".join(name_tokens(name))


def name_score(a: list[str], b: list[str]) -> float:
    if not a or not b:
        return 0.0
    if sorted(a) == sorted(b):
        return 1.0
    sa, sb = set(a), set(b)
    overlap = len(sa & sb) / len(sa | sb)
    chars = SequenceMatcher(None, " ".join(a), " ".join(b)).ratio()
    return round(0.6 * overlap + 0.4 * chars, 3)


# ---- VAT numbers and IBANs -------------------------------------------------------------------------
def valid_vat(value) -> bool:
    return re.fullmatch(r"3[0-9]{13}3", vat_key(value)) is not None


def iban_key(value) -> str:
    return re.sub(r"[\s\-.]", "", normalize(str(value or ""))).upper()


def iban_problem(value) -> str | None:
    """None for a valid IBAN, otherwise what is wrong, in plain words."""
    k = iban_key(value)
    if not k:
        return "it is empty"
    if not re.fullmatch(r"[A-Z]{2}[0-9]{2}[A-Z0-9]{11,30}", k):
        return "it is not in IBAN form (two letters, two check digits, then the account)"
    if k.startswith("SA") and not re.fullmatch(r"SA[0-9]{22}", k):
        return "a Saudi IBAN has 24 characters: SA, 2 check digits and 20 digits"
    digits = "".join(str(int(c, 36)) for c in k[4:] + k[:4])
    if int(digits) % 97 != 1:
        return "its check digits do not match (mod-97)"
    return None


def saudi_iban(bank: str, account: str) -> str:
    """A valid Saudi IBAN for a 2-digit bank code and an 18-digit account (used for the demo data and tests)."""
    body = f"{bank:0>2}{account:0>18}"
    check = 98 - int("".join(str(int(c, 36)) for c in body + "SA00")) % 97
    return f"SA{check:02d}{body}"


# ---- the vendor book ----------------------------------------------------------------------------
class VendorBook:
    """All vendors and the names reviewers linked to them, ready for matching an invoice."""

    def __init__(self, vendors: list[dict], aliases: list[dict] = ()):
        self.vendors = sorted(vendors, key=lambda v: v["id"])
        self._names = []  # (tokens, vendor, what it is, the name as written)
        for v in self.vendors:
            if v.get("name_en"):
                self._names.append((name_tokens(v["name_en"]), v, "English name", v["name_en"]))
            if v.get("name_ar"):
                self._names.append((name_tokens(v["name_ar"]), v, "Arabic name", v["name_ar"]))
        by_id = {v["id"]: v for v in self.vendors}
        for a in aliases:
            if a["vendor_id"] in by_id:
                self._names.append((name_tokens(a["alias"]), by_id[a["vendor_id"]], "linked name", a["alias"]))

    def __bool__(self) -> bool:
        return bool(self.vendors)

    def ranked(self, name: str | None) -> list[tuple[float, dict, str, str]]:
        """(score, vendor, matched on, matched name) for every vendor, best first; ties go to the lower id."""
        toks = name_tokens(name)
        best: dict[int, tuple[float, dict, str, str]] = {}
        for vt, v, what, written in self._names:
            s = name_score(toks, vt)
            if v["id"] not in best or s > best[v["id"]][0]:
                best[v["id"]] = (s, v, what, written)
        return sorted(best.values(), key=lambda x: (-x[0], x[1]["id"]))

    def match(self, fields: dict, min_score: float = DEFAULT_MIN_SCORE) -> dict:
        """Which vendor the invoice is from, how sure, and why. vendor is None when nothing matches well enough."""
        seller, vat = fields.get("seller_name"), fields.get("seller_vat")
        ranked = self.ranked(seller) if seller else []
        suggestions = [dict(id=v["id"], name_en=v.get("name_en"), name_ar=v.get("name_ar"), score=s) for s, v, _, _ in ranked[:3] if s > 0]
        if ranked and ranked[0][0] >= min_score:
            s, v, what, written = ranked[0]
            how = "matches exactly after normalising" if s == 1.0 else f"is close (score {s:.2f}, at least {min_score:.2f} needed)"
            why = f'Seller "{seller}" {how} the {what} "{written}" ({name_key(seller) or "-"}).'
            return dict(vendor=v, score=s, matched_on=what, why=why, suggestions=suggestions)
        if vat and vat_key(vat):
            for v in self.vendors:
                if v.get("vat") and vat_key(v["vat"]) == vat_key(vat):
                    why = f"No name matched well enough; the seller VAT number {vat_key(vat)} is this vendor's."
                    return dict(vendor=v, score=1.0, matched_on="VAT number", why=why, suggestions=suggestions)
        closest = f'; the closest is "{ranked[0][1].get("name_en") or ranked[0][1].get("name_ar")}" at {ranked[0][0]:.2f}' if ranked and ranked[0][0] > 0 else ""
        return dict(vendor=None, score=ranked[0][0] if ranked else 0.0, matched_on=None,
                    why=f'"{seller or vat or "-"}" is not in the vendor master{closest}.', suggestions=suggestions)


# ---- purchase orders -----------------------------------------------------------------------------
def po_match(fields: dict, po: dict | None, vendor: dict | None, tolerance: float = 0.01, field: str = "total") -> dict:
    """How the invoice stands against its purchase order. status is one of: no_po, not_found, vendor_mismatch,
    currency_mismatch, closed, over, matched."""
    number = (fields.get("po_number") or "").strip()
    if not number:
        return dict(status="no_po", detail="The invoice gives no PO number.")
    if not po:
        return dict(status="not_found", po_number=number, detail=f"PO {number} is not among the purchase orders.")
    out = dict(po_number=po["po_number"], po_amount=po["amount"], po_currency=po["currency"], po_status=po["status"],
               po_vendor=po.get("vendor_name"))
    amount = to_number(fields.get(field))
    cur = (fields.get("currency") or "").strip().upper()
    if po.get("vendor_id") and vendor and po["vendor_id"] != vendor["id"]:
        return dict(out, status="vendor_mismatch", detail=f"PO {number} belongs to {po.get('vendor_name')}, not this vendor.")
    if cur and po.get("currency") and cur != po["currency"].upper():
        return dict(out, status="currency_mismatch", detail=f"The invoice is in {cur}, PO {number} in {po['currency']}.")
    if amount is not None and amount > po["amount"] * (1 + tolerance) + 0.005:
        return dict(out, status="over", amount=amount,
                    detail=f"The invoice {field} {amount:,.2f} is above PO {number} ({po['amount']:,.2f}, tolerance {tolerance:.0%}).")
    if po.get("status") == "closed":
        return dict(out, status="closed", amount=amount, detail=f"PO {number} is closed.")
    return dict(out, status="matched", amount=amount, detail=f"Within PO {number} ({po['amount']:,.2f} {po['currency']}).")


# ---- validation and CSV ---------------------------------------------------------------------------
def clean_vendor(row: dict) -> tuple[dict, list[str]]:
    """A vendor ready to store, and what is wrong with it (empty if nothing)."""
    v = dict(name_en=(row.get("name_en") or "").strip()[:150] or None, name_ar=(row.get("name_ar") or "").strip()[:150] or None,
             vat=vat_key(row.get("vat")) or None, iban=iban_key(row.get("iban")) or None,
             currency=(row.get("currency") or "SAR").strip().upper()[:3] or "SAR",
             status=(row.get("status") or "approved").strip().lower())
    errors = []
    if not (v["name_en"] or v["name_ar"]):
        errors.append("a vendor needs an English or Arabic name")
    if v["vat"] and not valid_vat(v["vat"]):
        errors.append("the VAT number must be 15 digits, starting and ending with 3")
    if v["iban"] and iban_problem(v["iban"]):
        errors.append(f"the IBAN is not valid: {iban_problem(v['iban'])}")
    if not re.fullmatch(r"[A-Z]{3}", v["currency"]):
        errors.append("the currency must be a 3-letter code such as SAR")
    if v["status"] not in STATUSES:
        errors.append("the status must be approved or blocked")
    return v, errors


_HEADERS = {"name": "name_en", "name_en": "name_en", "english_name": "name_en", "name_ar": "name_ar", "arabic_name": "name_ar",
            "vat": "vat", "vat_number": "vat", "iban": "iban", "currency": "currency", "default_currency": "currency",
            "status": "status", "po": "po_number", "po_number": "po_number", "vendor": "vendor", "amount": "amount"}


def read_csv(text: str) -> list[dict]:
    """Rows of a CSV with its headers mapped to our names (case, spaces and a BOM do not matter)."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    rows = []
    for raw in reader:
        rows.append({_HEADERS.get(re.sub(r"\s+", "_", (k or "").strip().lower()), k): (v or "").strip() for k, v in raw.items() if k})
    return rows


def clean_po(row: dict) -> tuple[dict, list[str]]:
    po = dict(po_number=(row.get("po_number") or "").strip()[:60], vendor_name=(row.get("vendor") or "").strip()[:150] or None,
              amount=to_number(row.get("amount")), currency=(row.get("currency") or "SAR").strip().upper()[:3] or "SAR",
              status=(row.get("status") or "open").strip().lower())
    errors = []
    if not po["po_number"]:
        errors.append("a PO needs a number")
    if po["amount"] is None or po["amount"] < 0:
        errors.append("the amount must be a number of 0 or more")
    if not re.fullmatch(r"[A-Z]{3}", po["currency"]):
        errors.append("the currency must be a 3-letter code such as SAR")
    if po["status"] not in PO_STATUSES:
        errors.append("the status must be open or closed")
    return po, errors
