# Checks against ZATCA e-invoicing fields

Wording everywhere: "checks against ZATCA e-invoicing fields". Never "compliant" or "certified".

## What exists and what changes

1. **VAT number** (15 digits, starts and ends with 3): the `vat_number` rule already exists and, since the last
   audit, accepts Arabic-Indic digits and spaces. A missing seller VAT number is flagged by "Required fields present"
   (review); a malformed one by "Seller VAT number format" (reject). Extraction gains UBL and QR sources.
2. **VAT math**: `vat_rate` becomes aware of line VAT categories (UBL codes S standard, Z zero-rated, E exempt, O out of
   scope). VAT is checked against the rate times the standard-rated lines only; zero-rated and exempt lines carry no VAT.
   Without categories it behaves as before. `totals` already checks subtotal + VAT = total.
3. **Currency and numbers**: if an invoice prints no currency at all, the reader assumes SAR and says so in a note.
   Arabic-Indic digits and the Arabic decimal and thousands separators are already normalised; tests cover them.
4. **Dates**: `parse_date` reads Hijri dates (a year from 1300 to 1600, or a هـ / AH mark) and converts them to Gregorian
   with the Umm al-Qura calendar. No library and no download: `tools/build_hijri_table.mjs` writes the month table
   (1420 to 1500 AH) from the ICU data in the local Node, into `src/invoice_desk/hijri.py`. Future dates are flagged by
   the existing date rule.
5. **QR code**: read QR codes from images and PDF pages. No maintained pure-Python QR *reader* is known to me, and I
   will not browse for one, so: a small reader of our own for clean, upright codes (digital PDFs and screenshots, not
   phone photos), using the pure-Python `qrcode` package (from pip, added to the dependencies with Pillow) for the QR
   tables and to verify every read by re-encoding it. The TLV payload is compared to the fields, now including the
   timestamp's date. New rule type `qr_present` (default rule "QR code present", severity info, so a warning).
6. **UBL 2.1 XML**: `.xml` uploads are parsed directly (no AI), into the same fields, then the same rules. Any DOCTYPE
   or ENTITY declaration is refused before parsing, so there are no external or expanding entities.

## Rules, data, evaluation, docs
- New and changed rules appear on the Rules page in English and Arabic and work with versions, dry runs and rollback.
  Existing databases keep their rules; fresh or reset ones get the new defaults.
- Sample generator: the PDF and image samples currently carry a placeholder QR ("DEMO INVOICE QR"); they get the real
  TLV payload so the new reader is tested on them. A new ZATCA set (good and bad case per check, including XML) is
  appended with its own random seed, so the original 60 keep their content and answers.
- Evaluation and Intake list the new formats and scenarios. README: a section on what is and is not checked (no
  signature, hash chain or certificate checks, no Fatoora submission), and refreshed measured numbers.

## Commits
Plan; dates and VAT categories; UBL XML; QR reading; samples, evaluation, Rules labels and README.
Per commit: pytest, type check, i18n check. Browser checks once at the end.
