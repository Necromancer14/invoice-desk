# Readable XML invoices, PDF demo samples, re-shot launch assets

## Problem

For a UBL XML invoice the document pane (review and run detail) shows the XML source. A finance reviewer cannot read
it, and it makes the product look like a developer tool.

## 1. Readable invoice view

- `ubl.view(blob)` reads the parts of a UBL 2.1 invoice a person looks at: type, number, dates and time, currency,
  seller and buyer (name, VAT number, postal address when present), the lines (description, quantity, unit price,
  VAT category and rate, line total), subtotal, VAT and total, IBAN, PO reference and the QR payload. Same safety
  as `ubl.read`: DOCTYPE and ENTITY are refused before parsing.
- `GET /api/runs/{id}/invoice` (viewer) returns it for an XML run; 404 for any other file type, 422 when the XML
  cannot be read. Read only; nothing is stored.
- The portal's `Document` renders it as an invoice on the paper surface: title and number, dates, the two parties
  side by side, the lines table, totals, payment details, PO reference and the decoded QR code. Labels in English
  and Arabic, mirrored in Arabic; names keep their own direction; numbers, codes, IBANs and amounts are isolated
  left to right with tabular figures. A "Show source XML" toggle (closed by default) holds the indented source.
  If the view cannot be loaded the source is shown as before.

## 2. PDF versions of three demo samples

`tools/generate_data.py --pdf-copies` adds inv-090 to inv-092: PDF versions of inv-084 (changed IBAN), inv-075
(wrong VAT number) and inv-077 (QR code mismatch), with the same data apart from a new invoice number (so loading
both is not a duplicate), with IBAN and PO number printed and the QR code as an image. The generator asserts each
copy gets the same expected decision as its source. Existing files are not touched; a full regeneration also
produces the copies. The welcome set uses the PDFs instead of those three XML files (same decisions, so the
dashboard still shows 11 approved, 6 to review, 3 rejected).

## 3. Launch assets

Re-shoot the full and short videos and both thumbnails from a fresh server. The story uses the PDF samples; the
remaining XML samples show the readable view. Every frame is checked for raw XML.

## Tests

- pytest: `ubl.view` on written invoices (parties, lines, totals, IBAN, PO, QR, addresses, refused DOCTYPE), the
  endpoint (XML, non-XML 404, roles), and the PDF copies (read by the built-in reader to the same decision).
- `tools/ui_check.py`: an XML run shows the invoice view and no source until the toggle is opened, in both
  languages.
