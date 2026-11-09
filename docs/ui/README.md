# UI overhaul: before and after

Every page in English and Arabic, light and dark, at 1360 × 860. `before/` is the portal at the start of the
`ui-overhaul` branch, `after/` is the end. Both were taken with the same script against a fresh server, so the data
is the same 20 welcome samples plus the built-in evaluation:

```bash
py tools/ui_shots.py docs/ui/after
```

File names are `<nn>-<page>-<lang>-<theme>.jpg`. Open `compare.html` in a browser to flip through the pairs side by
side. The plan and the audit behind the changes are in `docs/plans/ui-overhaul.md`.

Note: the bundled PDFs show as a blank white page in these screenshots because headless Chromium does not render
PDFs inside an iframe. In a normal browser the PDF appears.

## What changed, page by page

**Everywhere (foundations).** One set of design tokens in `web/src/styles.css`: colours, type scale, 4 px spacing,
radius by hierarchy (6 controls, 8 panels, 12 dialogs), two shadows. The frosted glass and green colour blobs are
gone: surfaces are solid, so text and numbers sit on one known background. IBM Plex Sans with IBM Plex Sans Arabic,
self-hosted in `web/public/fonts` (SIL Open Font License), replace Figtree and Noto Sans Arabic; Arabic gets a taller
line height. Tabular figures on the whole page. One status palette: green approved, amber needs review, red rejected
or failed, solid dark red for high risk (so it never looks like a plain rejection), blue for queued and informational.
The sidebar is flat with a brand bar on the current page. A pytest (`tests/test_ui_tokens.py`) fails if a colour is
hard-coded outside the tokens or a font is loaded from outside the app.

**Run detail (`05`).** A wide sheet instead of a narrow dialog: the original on one side, the checks and evidence on
the other (mirrored in Arabic). The header names the seller with the total on the far side. Failed checks come
first, high risk on top, each with its reason and whether it rejects or sends to review; passed checks fold into
"Passed checks (n)".

**Review queue (`06`).** A workstation: a dense two-line list (seller and amount, then number, failed count and
age), amounts aligned, the high-risk mark beside the name, the open invoice marked with a brand bar. The selected
invoice shows the document beside "Why this needs a person", the fields and the evidence. Approve and Reject sit in
a decision bar that stays on screen while scrolling, with the j/k/a/r shortcuts shown beside them.

**Dashboard (`02`).** The share cleared without a person is the headline, with received, waiting, fixed and time to
decide beside it. Then the status bar in the shared status colours with counts in the legend, then the detail.
"Invoices per day" no longer looks broken when everything arrived on one day: the scale has a floor of 4 and a
whole-number halfway mark, empty days are faint ticks on the baseline, and the busiest day carries its count.
"Rules that fail most" uses a neutral data colour instead of borrowing a status colour.

**Runs (`04`).** Hairline rows instead of floating pills, about twice as many rows per screen. Every heading sorts
(numbers and dates newest or largest first, text A to Z) and says so with `aria-sort`. Status chips, muted ids and
file names, bold amounts. Names keep their own direction in both languages.

**Welcome card and demo note (`01`).** Same text and buttons. The card is a plain panel with a brand rule on its
inline-start edge; the demo note is one quiet line with an amber mark.

**Rules (`07`, `08`).** One list in the order the rules run, instead of 20 separate cards; quieter move controls;
version history as rows. The rule editor dialog picks up the new controls.

**Vendors (`09`).** Shared toolbar, actions in a real table cell (the row borders no longer break), purchase order
status as a tag, linked-name counts aligned as numbers.

**Evaluation (`10`), Settings (`12`), Upload (`03`), Audit log (`11`), sign-in (`00`).** Token spacing instead of
inline pixel values; Settings puts the demo reset in its own panel and aligns the theme and language rows; the audit
action codes use the code face.
