# Demo history and dashboard v2

Phases A and C of `docs/plans/demo-maturity.md`. Look stays the "ledger desk" style; only layout and interaction
patterns are borrowed from the Lumelle reference.

## 1. Demo history (backend)

- "Load sample invoices" now loads two groups, in date order, through the normal pipeline (built-in reader):
  - **History**: every text, PDF or XML sample that is not in the welcome set, not a planned duplicate and not the
    original of a PDF copy in the welcome set. Spread over days 2 to 29 before today, so the last week has decisions by a person too. The ones that land in review
    are decided by two made-up reviewers (`noura`, `faisal`): approved, or rejected with the scenario as the note.
  - **Welcome set**: the same 20 as before (11 approved, 6 to review, 3 rejected), spread over the last 7 days, with
    the 6 waiting for review in the last 2 days.
- A run is backdated by shifting every timestamp it has (created, updated, decided, trace steps, audit rows) by the
  same amount, and a human decision gets a believable delay (20 minutes to a day).
- Runs are inserted first and processed one by one in a single background job, so ids follow dates, the duplicate
  check sees runs in date order, and the dashboard polls while anything is queued.
- `POST /api/samples/demo` takes `{"history": false}` to load only the welcome set.
- The demo note and welcome card say the history is sample data spread over 30 days.

## 2. Stats for a period (backend)

`GET /api/stats?source=upload&days=30` (7, 30 or 90) adds a `period` block; the existing fields stay as they are.

- `current` and `previous` (the window of the same length before it): received, auto-cleared rate, approved by a
  person, rejected, average time to decide, value approved / waiting / rejected in SAR, invoices in other currencies.
- `series`: per day in the window, counts by outcome (auto, person, review, rejected) and SAR value received.
- `waiting`: the 5 longest-waiting review items (id, seller, number, total, currency, created, high risk).
- `due_soon`: approved invoices with a due date in the next 7 days: count and SAR value.
- `insight`: the rule whose failures rose most against the previous window (at least 2 more), or none.
- `GET /api/activity?limit=8`: recent audit rows a person would care about (reviews, rule, vendor and settings
  changes, demo loads, reprocessing), with seller and invoice number attached for review rows.

## 3. Dashboard (portal)

1. Greeting band: "Good morning, <name>" and one sentence built from real counts (waiting, high risk, due this
   week), parts linking to the review queue. Buttons: Upload invoices, Open review queue.
2. Period switch (7, 30, 90 days) beside the source filter.
3. Four figures with change against the previous window and a sparkline: received, cleared without a person,
   value approved (SAR), average time to decide (down is good).
4. Stacked area chart by outcome per day (hand-written SVG), legend toggles a series, a list for screen readers.
5. "Waiting longest" list with Open buttons, and a money panel (approved, waiting, rejected in SAR).
6. Rules that fail most and top rejection reasons, for the period.
7. Activity feed and AI usage.
8. Insight card when there is one, with a link to Rules.

Motion: figures and chart fade in; nothing moves with `prefers-reduced-motion`. Every string in English and
Arabic; amounts and codes stay left to right in Arabic.

## Tests

- Demo load: welcome set still 11 / 6 / 3, history decided, review queue holds only the 6, dates within 30 days,
  ids in date order, audit rows backdated, `history: false` loads 20.
- Stats period: windows, previous window, deltas inputs, SAR sums, other currencies, due soon, waiting order,
  insight.
- Activity: filtered actions, seller attached.
- Portal: `ui_check.py` and `a11y_check.py` cover the new dashboard in both languages and themes.
