# Fixes and self-audit

Branch `dev`. One commit per step below, each after the full check (tests, type check, build, `tools/check_i18n.mjs`).

## Known issues

1. **Mixed-direction names in tables.** In the English Runs table an Arabic seller name lines up at the wrong edge of its
   column. The CSS rule that was meant to fix this (`text-align: match-parent`) has no effect in Chromium. Fix: put names
   in an inner element with `dir="auto"` (so the ellipsis falls at the name's own end) and align that element by the
   page direction with an explicit rule, in the Runs table and the review list.
2. **Review badge lags.** The sidebar count only refreshes every 8 seconds, so after uploads (processed in the
   background) or a decision it can show an old number. Fix: lower the count at once when a decision is made, refetch
   right after, refetch quickly while invoices are still queued or processing, and keep it in step with the Review page's
   own list.
3. **Slow first load on Render's free tier.** Fix: if `/api/health` has not answered after a few seconds, show a
   "waking up the demo" screen (English and Arabic) that keeps retrying for up to about 90 seconds, then offers a retry
   button. Limit to state plainly: the page itself is served by the same sleeping server, so on a fully cold start the
   browser waits for Render before any of this code runs. The screen helps when the page is up but the API is slow or
   restarting.

## Self-audit, found by probing the code (`py` script against the real modules and a test client)

Rules engine
- A VAT number in Arabic-Indic digits (`٣٠٠…٣`) or with spaces (`300 000 000 000 003`) or padding is **rejected** as
  malformed. Fix: normalise digits and drop spaces before the format check.
- Negative totals are **auto-approved** when the arithmetic agrees. Fix: `amount_limit` gets an optional `min`, and a
  new default rule "Total is not negative" (review severity) uses it. Existing databases keep their rules; new and reset
  ones get it.
- A field holding only spaces counts as present. Fix: treat whitespace-only as missing.
- Currency `" sar "` is treated as foreign. Fix: strip and compare case-insensitively (already upper-cased).
- Duplicate detection misses the same invoice when the number differs in case or spacing, or the VAT number is written
  in Arabic digits. Fix: compare normalised values. Same seller and number in another currency stays a duplicate, on
  purpose: it is the same invoice number from the same seller.
- `to_number` turns an accounting negative `(100.00)` into `100`, and a non-finite float (`inf`, `nan` from a model's
  JSON) passes through. Fix: parentheses mean negative; non-finite becomes "missing".
- Very large amounts were checked and behave (absolute tolerance holds at 1e16); a test keeps it that way.

API
- `POST /api/rules/rollback` with a non-number version crashes with a 500. Fix: 400 with a message.
- `limit` and `offset` on `/api/runs` and `/api/audit` accept negative and huge values (`limit=-1` returns every row).
  Fix: clamp to 1..200 / 1..500 and offset >= 0.
- `/api/samples/submit` with `files` as a string walks its characters. Fix: require a list of names.
- No length limits on rule name, message and note, or on a review note. Fix: 120 / 300 / 500 / 2000 characters.
- Uploaded file names keep control characters and path parts. Fix: clean the name on intake (the download header was
  already escaped by Starlette, so this is tidiness, not an injection).
- Uploads are read fully into memory before the 5 MB check. Fix: check the size Starlette already knows first.
- A damaged PDF fails with `PdfStreamError: Stream has ended unexpectedly`. Fix: "This PDF could not be opened. It may be
  damaged or not really a PDF." (the technical detail stays in the trace).

UI error states
- `api()` has no timeout, so a hung request spins for ever. Fix: abort after 30 s (uploads 120 s) with a clear message.
- Network failure, 429 and 5xx show raw text such as "Failed to fetch". Fix: plain messages, translated.
- Check provider failure and a malformed file end to end in the browser.

Accessibility (English and Arabic, light and dark)
- Run axe-core (added as a dev dependency) over the main pages from a Playwright script, and fix what it reports.
- Keyboard: modals should take focus when they open and give it back when they close; the review list uses
  `role="listbox"` without arrow-key support, so make it a plain list of buttons with `aria-current`.
- Check focus outlines and colour contrast of muted text and status pills in both themes.

## Not in scope
- Translating server error messages (they stay English, as before).
- A separate always-on status page for the Render cold start.
