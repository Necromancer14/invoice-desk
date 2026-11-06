# Vendor master and purchase order matching

## Data
- New tables: `vendors` (English and Arabic name, VAT number, IBAN, default currency, status approved/blocked),
  `vendor_aliases` (a seller name a reviewer linked to a vendor) and `purchase_orders` (PO number, vendor, amount,
  currency, status open/closed). Vendor master changes are audited; they are data, not rule versions.
- Two new invoice fields, `iban` and `po_number`, read by the rule-based reader, UBL XML (PayeeFinancialAccount,
  OrderReference) and AI models. Not scored by the evaluation, so its figures stay comparable.
- Validation: VAT as today; IBAN for Saudi Arabia is 24 characters, starts with SA, and passes the ISO 13616 mod-97
  check. Other countries' IBANs get the mod-97 check and a length of 15 to 34.

## Matching (`vendors.py`, no AI)
- Normalise a name: case, spacing, punctuation, Arabic diacritics and tatweel, letter variants (أ إ آ to ا, ة to ه,
  ى to ي), Arabic-Indic digits, the article (ال, لل) and legal words (LLC, Ltd, Co., Est., شركة, مؤسسة, ذ.م.م...).
- Compare against each vendor's English name, Arabic name and linked aliases: exact after normalising scores 1.0,
  otherwise 0.6 x token overlap + 0.4 x character similarity. The best vendor wins; ties go to the lower id. If no
  name scores 0.85 or more, an exact VAT number match identifies the vendor. Every match says what it matched on.
- "Al Rajhi Trading" and "الراجحي للتجارة" map to one vendor because the vendor record holds both names; no
  transliteration is attempted.

## Rules (new types, default rules)
Unknown vendor (review), Blocked vendor (reject), Seller VAT number differs from vendor master (review), IBAN differs
from vendor master or is invalid (review, marked high risk with a fraud warning), Invoice above the PO amount (review,
tolerance default 1%, compared field configurable). All skip when the vendor master is empty or the field is missing.

## Portal
Vendors page (list, add, edit, delete, CSV import) with a Purchase orders section (list, CSV import, delete). Run
detail shows the vendor match (score, what matched, why) and the PO match status, with "Link to vendor" for a
reviewer. The review list marks high-risk invoices. Everything in English and Arabic.

## Seeds, samples, docs
The generator writes `data/samples/vendors.csv` and `purchase_orders.csv` (the 12 sample sellers, one blocked vendor,
POs) and appends samples for each rule. The app seeds a fresh or reset database from them; tests start empty.
README: what is checked and what is not (no bank verification, no live vendor or VAT lookup).

## Commits
Plan and XML cleanup; backend with tests; portal; samples, evaluation and README. Browser checks once at the end.
