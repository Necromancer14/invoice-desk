# Demo maturity: what we can take from Lumelle, and an agentic layer

Reference: https://demo.codeandchill.store/lumelle/ (reviewed 9 Nov 2026). Lumelle is a paid admin dashboard template
for a made-up candle shop ("Saltmarsh Candle Co."). Every figure is canned front-end data; there is no backend.
So it is a reference for presentation and interaction, not for function. Our product already does far more real work.
The gap is that Lumelle *feels* like a product someone runs a business on, and our portal still feels like a
well-built tool page by page.

## 1. What makes Lumelle feel mature

Seen on the Overview, Orders list, order drawer, search palette and notifications.

**It talks to you about today, not about the data.**
- Greeting with one actionable sentence: "Friday 30 October · **10 orders** to pack, and **Fig Leaf Diffuser** is
  running low." The bold parts are links.
- An "Insight" card at the bottom: a finding in plain words plus one button ("Plan a send").
- A daily goal ring ("£600 of £1,600 · 8 orders so far"), also pinned at the foot of the sidebar.

**Every number has context.**
- Period switcher (Today, 7 days, 30 days, 12 months) on the main chart.
- Each KPI tile shows a delta against the previous period (↓ 9.5%) and a small sparkline.
- The main chart is a stacked area by channel, with a legend that doubles as a toggle.

**Work queues have the action on the row.** "Packing queue" lists orders with a progress stepper and a Pack
button per row; "Running low" has a Pour button per product. You act without opening anything.

**Shell features that every page shares.**
- Command palette (search icon, also keyboard): one box across orders, products, customers and pages, with
  keyboard hints (move, open, pack or ship).
- Notifications panel with unread dots and "Mark all read"; events link to the thing they are about.
- Global "+ New" button, breadcrumbs ("Saltmarsh Candle Co. > Orders > All orders"), live indicator
  ("23 on the shop").
- Icon-rail sidebar with badge dots; bottom tab bar on phones.

**Lists are workbenches.**
- Summary tiles above the table (6 to pack, 4 ready to ship, 5 unpaid, 3 returns open), each a filter.
- Status tabs with counts (All 582, To pack 6, Packed 4 ...), channel chips, search, Export, "Show 25 more" with a
  running total ("25 of 582 · £40,092").
- Detail opens in a side drawer over the list (deep-linkable `#/orders/all/4687`) with status chips, line items,
  totals, customer, delivery, a **timeline**, and actions in a sticky footer.

**Activity feed.** "Team activity: Tomasz packed 14 online orders", each line a link.

**Material.** Dark glass panels over large blurred colour blobs, pink accent, rounded 20 px corners, motion on
load (numbers and bars animate in).

## 2. Our product today, side by side

| Area | invoice-desk now | Lumelle pattern | Gap |
|---|---|---|---|
| Home | Dashboard: cleared %, four figures, status strip, top failing rules, rejection reasons, invoices per day, AI usage | Greeting + "what needs you", period switch, deltas, sparklines, goal, insight | No "today" sentence, no period, no deltas, no money figures, chart looks empty on demo data |
| Money | Totals per invoice only | Revenue front and centre | We never show SAR amounts in aggregate: value approved, value held in review, value blocked |
| Queue | Review queue with list, preview, reasons, j/k/a/r | Inline row actions, steppers | Strong already. Missing: age/SLA, "oldest waiting", bulk approve of low-risk items |
| Lists | Runs table, sortable, search | Tiles, status tabs with counts, chips, export, load more with total | No tabs with counts, export is API only (`/api/export.csv`), no running total |
| Detail | Run detail as a dialog; review split view | Drawer with timeline and sticky actions | No per-invoice timeline although the audit log has every event |
| Global | Sidebar, theme, language | Command palette, notifications, "+ New", breadcrumbs | All four missing |
| Vendors | List, add, edit, import, link in review | Customer and product pages with history | No vendor profile (history, totals, failure rate, IBAN changes) |
| Activity | Audit log page (table) | Human-readable feed on home | Audit data exists, not shown as a feed |
| Phone | Responsive | Bottom tab bar | Fine; bottom bar optional |
| Quality | EN/AR with RTL, axe checks in light and dark, tests, evaluation against an answer key | None of this | Our real advantage. Keep it visible |

Things we do that Lumelle cannot, and should show off more: Arabic RTL, the rule engine with versions and dry run,
the evaluation page with a ground-truth answer key, ZATCA field and QR checks, IBAN mod-97, bring-your-own AI key,
MCP server.

Noticed while comparing: in `docs/ui/after/06-review-en-dark.jpg` the document pane is blank white. It may be
screenshot timing on a PDF, but a blank original on the main work screen is the single most "unfinished" looking
thing in the demo, so it is the first item to check.

## 3. Visual direction: borrow structure, not the glass

`docs/plans/ui-overhaul.md` deliberately moved us **away** from glass and colour blobs, because text contrast varied
across a panel and it read as less trustworthy for finance users. Lumelle is exactly that material. Copying it
would undo that work and fail our own axe checks in places.

Recommendation: keep the "ledger desk" tokens (solid surfaces, one green, Plex, tabular figures) and import
Lumelle's **layout and interaction** patterns, plus a few places where we can spend some richness safely:

- A header band on the dashboard only: a soft green gradient behind the greeting, with text on a solid tint so
  contrast stays fixed.
- Area charts with a gradient fill under the line (hand-written SVG, no chart library, per CLAUDE.md).
- Number count-up and bar grow on first load, honouring `prefers-reduced-motion`.
- Status chips with a leading dot, row hover lift, drawer slide-in.
- Icon-rail collapse for the sidebar (keeps labels on hover and in the expanded state).

If the owner wants the full glass look anyway, do it as an opt-in third theme ("Showcase") so the default stays
the accessible one. That is a business call, listed under decisions below.

## 4. Changes that make the POC look mature

Ordered by effect on a first-time visitor.

### Phase A: demo data that tells a story (small, highest effect)
- Seed the sample set across the last 30 days instead of all "today", so the daily chart, deltas and sparklines
  have shape. Keep `answers.json` untouched; only `created_at` in the demo loader changes. Label it in the demo
  note ("sample history spread over 30 days").
- Add `decided_at` and reviewer names for a handful of past human decisions so "average time to decide" and the
  activity feed are not empty.
- Fix or confirm the blank PDF pane.

### Phase B: the shell
- **Command palette** (Ctrl+K and a search button): runs by number, invoice number, seller; vendors; rules; pages;
  actions ("Upload invoices", "Load sample invoices", "Export CSV"). New endpoint `GET /api/search?q=` in `api.py`,
  logic in `desk.search()`.
- **Notifications**: derived from the audit log and runs, no new store needed at first: new items in review,
  high-risk items, IBAN mismatch, evaluation finished, rule changed. Unread state per user in local storage.
- **Global "+ Upload"** button and **breadcrumbs** in a top bar.

### Phase C: dashboard v2 ("Today at the desk")
- Greeting line built from real counts: "Monday 9 November · **6 invoices** need a person, **1 is high risk**, and
  **SAR 412,000** is due this week." Each bold part links to a filtered view.
- Period switcher (Today, 7, 30, 90 days) on `GET /api/stats?days=`; every figure gets a delta against the previous
  period of the same length, and a sparkline.
- Money figures: value approved, value waiting for review, value rejected. Rejected value is the honest version of
  "what the checks stopped"; word it as "rejected", not "fraud prevented".
- Stacked area of invoices per day by outcome (auto, by a person, review, rejected).
- "Oldest waiting" and "Due soon" mini-queues with inline Approve/Open, like Lumelle's packing queue (approve only
  for reviewers, still behind the same review endpoint and audit).
- Activity feed from the audit log, in plain sentences, translated.
- Insight card (see the agentic section; a non-AI version first).

### Phase D: lists and detail
- Runs: summary tiles, status tabs with counts, source chips, Export button, "Show more" with running total in SAR.
- Run detail as a side drawer with a **timeline** (received, read by which reader, checks run with rules version,
  routed, edited fields, decided by whom, re-processed) built from the audit log plus run fields.
- Vendor profile page: invoices, totals by month, failure rate, last IBAN and any change, open POs.

### Phase E: review power features
- Age and SLA marker per item (setting: hours before an item counts as late).
- Bulk approve for items whose only failures are "review" severity rules the admin marks as bulk-safe (off by
  default). Every item still gets its own audit row.
- Claim/assign ("Noor is looking at this") so two reviewers do not collide.

Each phase follows the repo gate: tests for every change, EN and AR strings, RTL check, `ui_check.py` and
`a11y_check.py` for portal changes, rebuilt `web/dist`.

## 5. Can it be agentic? Yes, in ways that fit the product

Principle: **the agent investigates and proposes; the rules and a person decide.** An AI agent never approves or
rejects on its own. That keeps the honesty rules in CLAUDE.md intact and is what a finance buyer wants to hear.
Every agent step is written to the audit log with actor `agent:<provider>`, the AI key stays per request and is
never stored, and the existing guard against instructions hidden in documents applies to anything the agent reads.

Today the providers only do one-shot extraction. An agent needs tool calling in `providers.py` (Anthropic, OpenAI,
Gemini, Groq and OpenRouter all support it; Ollama depends on the model), and a small loop in a new
`agent.py` with a step limit and a fixed tool list. Tools are thin wrappers over `Desk` methods that already exist.

| Tool | Backed by |
|---|---|
| `get_invoice(id)` | `get_run`, `invoice_view` |
| `find_vendor(name or vat)` | `vendor_book`, `vendors.py` matching |
| `get_po(number)` | `po_by_number` |
| `similar_invoices(id)` | duplicate check data (same seller, amount, number) |
| `vendor_history(vendor_id)` | runs by vendor |
| `reread(id, provider)` | `reprocess` with a vision model |
| `simulate_rule(rule)` | `simulate` (dry run) |
| `propose(...)` | writes a proposal record; never changes status |

### Agent features, in order of value for the demo

1. **Review copilot ("Investigate")** on each review item. It runs the tools, then writes a short finding with
   evidence links: "IBAN differs from the vendor master (ending 4471 vs 0932). This vendor's last 12 invoices all
   used 0932. Recommend: reject and contact the vendor." Shows as a panel above the decision bar with the steps it
   took. The reviewer still presses Approve or Reject.
2. **Rule writer.** On the Rules page: "Send invoices from vendors we have never paid above SAR 20,000 to review."
   The agent produces a rule using our rule types or the safe `expression` type (already AST-checked), runs the
   dry run, and shows "would change 4 of the last 300 decisions" before the admin saves. This uses
   `simulate` and rule versions, two of our strongest features, and is very demo-able.
3. **Auto-fix proposals.** When extraction confidence is low, the agent re-reads with a vision model and proposes
   field corrections as a diff the reviewer accepts in one click. Corrections are already stored beside the
   original extraction.
4. **Vendor message draft.** For a rejection, draft the note to the vendor in English and Arabic from the failed
   checks. Copy button only; nothing is sent.
5. **Ask the desk.** In the command palette: "How much is waiting for review from Sahara Fleet?" answered with tool
   calls over stats and runs, with links to the rows.
6. **Weekly digest / Insight card.** A deterministic version first (no key needed): "Rejections for wrong VAT rate
   doubled this week, mostly from 2 vendors." With a key, the agent phrases it and suggests a rule.
7. **MCP write tools.** Extend `mcp_server.py` with `submit_invoice`, `review_queue`, `propose_decision`, so
   Claude Desktop or Claude Code can work the desk as an agent. Decisions still need a person in the portal.

### Without an AI key
The demo runs keyless by default. Give the copilot a **rule-based mode** that runs the same tools deterministically
(vendor lookup, history, PO, duplicates) and fills a template finding. The panel then works for every visitor, and
the AI version is an upgrade, not a requirement. Label which mode produced each finding.

### Measuring it
We have a ground-truth answer key. Extend `evaluation.py` to score copilot recommendations against
`answers.json`: agreement with the correct decision, unsafe "approve" recommendations, and steps and tokens per
item. Show it on the Evaluation page. This is a stronger maturity signal than any visual change, and it must be
worded as measured on synthetic samples only.

## 6. Suggested order

| Step | Size | Why first |
|---|---|---|
| A. Demo data spread over 30 days, blank PDF check | S | Every later screen depends on data with shape |
| C. Dashboard v2 (greeting, period, deltas, money, feed) | M | The first screen people see |
| B. Command palette, notifications, top bar | M | Shell polish visible on every page |
| 5.1 Review copilot, rule-based mode first, then AI | M to L | The agentic story, works without a key |
| 5.2 Rule writer with dry run | M | Best single demo moment for admins |
| D. Runs tabs, drawer with timeline, vendor profile | M | Depth for people who click around |
| 5.x Evaluation of the copilot | S | Proves the agent rather than claiming it |
| E, 5.3 to 5.7 | M each | After the core is in |

## 7. Decisions for the owner

1. **Look:** keep the ledger style and borrow Lumelle's layout and motion (recommended), or add Lumelle-style glass
   as an opt-in "Showcase" theme, or switch the default to glass.
2. **Demo history:** OK to backdate sample invoices across 30 days in the demo loader, clearly labelled?
3. **Agent provider scope:** start tool calling with Anthropic and Gemini only (Gemini has a free key), or all
   providers at once?
4. **Bulk approve:** include it at all? It speeds review but is the feature most likely to worry an auditor.

### Owner decisions (10 Nov 2026)

1. **Look:** keep the ledger style. Borrow Lumelle's layout and motion only. No glass, no "Showcase" theme.
2. **Demo history:** approved. Sample invoices are dated over the last 30 days by the demo loader, and the demo note
   says so. `answers.json` is not touched.
3. **Agent provider scope:** tool calling starts with Gemini plus a rule-based mode that needs no key. Other
   providers come later.
4. **Bulk approve:** not built. Phase E drops it.

Build order agreed: Phase A, then a trimmed Phase C (greeting with real counts, period switch Today / 7 / 30 / 90 days
with change against the previous period, SAR totals for approved, waiting and rejected, stacked area chart by
outcome, "Oldest waiting" with Open buttons, activity feed; count-up and bar motion honour reduced motion), then from
Phase D only the per-invoice timeline in run detail.
