# UI overhaul

Audience: finance and accounts payable managers in Saudi Arabia, and technical hiring managers looking at the demo.
Goal: calm, credible, finance-grade. No feature or API changes.

Screenshots of the current portal (every page, English and Arabic, light and dark) are in `docs/ui/before/`,
taken with `py tools/ui_shots.py docs/ui/before` against a fresh server.

## Audit

### What works

- The information is right. Every screen answers a real question (what came in, what failed, who decided).
- Status pills already pair an icon with a word, so status never depends on colour alone.
- Bidirectional text is handled with care: names keep their own direction (`dir="auto"`), codes and amounts stay
  left-to-right inside Arabic, and the layout mirrors with logical properties.
- The review queue already has a list beside the selected invoice and j/k/a/r shortcuts.
- Keyboard and screen reader basics are in place (focus trap in dialogs, named regions, axe checks).

### What does not

**Material.** Frosted glass on every surface, over large green colour blobs. Text and numbers sit on a background
that changes from one part of the screen to the next, so contrast varies across a single panel. In dark mode the
blobs read as a green haze; in full-page screenshots they stop at the first screen and leave a hard edge.

**Hierarchy.** Everything has the same weight: rounded glass card, 22 px padding, bold heading. On the dashboard
the five figures are equal tiles, so nothing says "this is the number to look at". Page subtitles run to two or
three lines and push content down.

**Density.** Table rows float as separate rounded pills with 7 px gaps and 11 px padding; 20 runs need two screens.
The review list items take two to three lines each; a reviewer sees six invoices. Rule cards are 86 px tall each.

**Consistency.** Radius is 26, 22, 20, 18, 16, 14, 12, 10 and 99 px depending on the component. Buttons, chips,
segmented controls and pills are all full pills, so actions and labels look alike. Status colours are defined
twice: once as soft pills, once as gradient strip segments (`#19ac60`, `#f0b73e`, `#e8645a`) that do not match the
pills. "High risk" reuses the rejected pill, so it cannot be told apart from a rejection. Gradients are hard-coded
in a dozen places outside the variables.

**Numbers.** Amounts in the Runs table are not tabular (proportional figures in `td` without `.n`), and the review
list amounts are right next to the name with no column, so they do not line up. The dashboard figures use 28 px
Figtree, whose figures are geometric and less legible than a grotesque at small sizes.

**Run detail and review.** The run detail is a narrow 700 px dialog: the document, then the vendor, then the checks,
one under another. The failed checks are at the bottom, below the trace. In the review queue the Approve and
Reject buttons sit below thirteen fields and scroll off screen; the reasons the invoice is here are in a second
panel below that. Reject has no visible shortcut, and the shortcut legend is far away in the page header.

**Invoices per day.** The bars are scaled to the busiest day. When all invoices arrived today (the normal demo
case), thirteen days show as 3 px green stubs and one bar fills the chart, which looks like a rendering fault.
There are no counts and no axis.

**Arabic typography.** Figtree (Latin) and Noto Sans Arabic do not share proportions: Arabic looks small and light
next to the Latin, and Noto ships only 400 and 700 here, so the 600 and 650 weights used for labels jump to 700.
Line height 1.5 is tight for Arabic with its taller ascenders and descenders, especially in the 13 px muted text.

## Design direction: "the ledger desk"

A working tool for people who read numbers all day. Solid surfaces, quiet borders, one green, and figures that line
up. The one place the design spends its boldness is the numbers: large, tabular Plex figures for the headline
count and amounts, set against plain, low-contrast chrome. Everything else stays out of the way.

- Surfaces are solid paper on a slightly cooler page. No blur behind text. Separation comes from a 1 px line and
  a change in surface, not from shadow.
- Green is the brand and the primary action. It is not used for decoration.
- Four status colours, defined once and used everywhere (pills, strip, legend, bars, check marks, list marks).
- Tables and lists are tables and lists: hairline rows, 36 to 40 px tall, aligned numeric columns.
- Small radii that follow hierarchy: controls 6, panels 8, dialogs 12. Pills keep a full radius only for status
  chips, so a status never looks like a button.

### Colour tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f3f5f4` | `#0e1412` | page |
| `--surface` | `#ffffff` | `#151c19` | panels, tables |
| `--surface-2` | `#f7f9f8` | `#1b2420` | table heads, hover, inset areas |
| `--line` | `#e1e6e3` | `#28322e` | hairlines |
| `--line-strong` | `#c8d0cc` | `#3a4641` | inputs, controls |
| `--ink` | `#14201a` | `#e5ebe8` | text |
| `--ink-2` | `#3c4a43` | `#c2ccc7` | secondary text |
| `--muted` | `#5b6a63` | `#93a19a` | labels, meta (4.5:1 or better on surface) |
| `--brand` | `#006c35` | `#3fbf7f` | primary action, current nav |
| `--on-brand` | `#ffffff` | `#06170e` | text on brand |
| `--ok` / `--ok-bg` | `#0b6b3a` / `#e6f3ec` | `#5fd398` / `#173225` | approved |
| `--warn` / `--warn-bg` | `#8a5300` / `#fdf1dc` | `#f2b75b` / `#33270f` | needs review |
| `--bad` / `--bad-bg` | `#b42318` / `#fdecea` | `#ff8f86` / `#3a1715` | rejected, failed |
| `--risk` / `--on-risk` | `#8f1d14` / `#ffffff` | `#ff6b5e` / `#1e0605` | high risk (solid, not soft) |
| `--info` / `--info-bg` | `#1f4f8f` / `#e8f0fb` | `#93bdf2` / `#172539` | queued, processing, informational |

Status strip and bars use the solid tones: `--ok`, `--ok-human` (a lighter green, `#6fbf94` / `#2f8f61`), `--warn-solid`
(`#d18a12` / `#d59a3a`), `--bad`. Text on each segment is chosen for 4.5:1.

### Type

- IBM Plex Sans (variable, Latin) with IBM Plex Sans Arabic (400, 500, 600, 700), self-hosted in `web/public/fonts`
  under the SIL Open Font License. The two were designed together, so weights and proportions match.
- Scale (px): 12 (meta), 13 (labels, table meta), 14 (body, tables), 16 (section heads), 20 (page title),
  28 (figures), 40 (headline figure). Line height 1.45 for Latin, 1.65 when the page is Arabic.
- Weights: 400 body, 500 labels and table heads, 600 headings and figures. No 650/750 synthetic weights.
- `font-variant-numeric: tabular-nums` on the body, so every amount, count and date lines up.
- Sentence case everywhere. No all-caps labels.

### Spacing, radius, shadow

- Spacing on a 4 px grid: `--s1` 4, `--s2` 8, `--s3` 12, `--s4` 16, `--s5` 24, `--s6` 32, `--s7` 48.
- Radius: `--r-sm` 4 (chips, kbd), `--r-md` 6 (buttons, inputs), `--r-lg` 8 (panels), `--r-xl` 12 (dialogs).
- Shadow: `--sh-1` `0 1px 2px rgb(16 24 20 / .06)` for panels in light mode only; `--sh-2`
  `0 12px 32px rgb(16 24 20 / .18)` for dialogs and toasts. No coloured shadows.

### Layout

```
+------------+-----------------------------------------------+
| invoice-   | demo note (thin, one line)                    |
| desk       | Title                        [filters] [act]  |
|            | one-line description                          |
| Dashboard  +-----------------------------------------------+
| Upload     |                                               |
| Runs       |   content: panels on a 1280 px max width      |
| Review  6  |                                               |
| ...        |                                               |
| ---------- |                                               |
| user, role |                                               |
| theme lang |                                               |
+------------+-----------------------------------------------+
```

A flat sidebar (surface colour, 1 px line at its inline end) replaces the floating glass column. Content is aligned
to the inline start; nothing is centred except empty states.

## Pages

1. **Run detail and review.** Split view: document on the inline-start side, sticky; fields and checks on the other.
   On the review side the order is: why it needs a person (failed checks first, with plain reasons and the high-risk
   mark), decision bar (Approve `a`, Reject `r` plus note, always visible as a sticky bar), editable fields, line
   items, then vendor, QR and trace. The Runs dialog becomes a wide two-column sheet with the same order.
2. **Review queue.** A workstation: dense list (one row: seller, amount right aligned; second line: number, failed
   count, high-risk mark, age), selected row with a brand bar on its inline-start edge, the preview beside it, and the
   shortcut legend next to the decision buttons. j/k/a/r stay as they are.
3. **Dashboard.** Headline: the share cleared without a person, large, with the received count beside it. Then the
   status bar (flat segments in the status colours, counts as a legend below). Then the detail: the other figures,
   rules that fail most, rejection reasons, invoices per day, AI usage. The daily chart gets a baseline, a count
   above each non-zero bar, empty days drawn as a faint tick, and a fixed minimum scale so one busy day looks like
   one busy day.
4. **Runs table.** Hairline rows, 40 px, sticky header, sortable columns (number, file, invoice number, seller,
   total, status, created) with `aria-sort`, status chips, and the existing `dir` handling kept.
5. **Welcome card and demo note.** Same content; the card becomes a plain panel with a green inline-start rule, the
   note a single quiet line.
6. **Rules, Vendors, Evaluation, Settings, Upload, Audit.** Tokens and the shared layout: rule cards become rows in
   one panel, tables use the new table style, settings and evaluation use the same panel and field styles.

## Checks

- Every commit: `py -m pytest -q`, `npm --prefix web run typecheck`, `node tools/check_i18n.mjs`, and the build.
- At the end, against a fresh server: `py tools/ui_check.py`, `py tools/a11y_check.py` (WCAG AA contrast in light
  and dark, English and Arabic), then `py tools/ui_shots.py docs/ui/after` for the before and after pairs.
