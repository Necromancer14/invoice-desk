# Review copilot (demo-maturity.md section 5.1)

Principle: **the agent investigates and proposes; the rules and a person decide.** The copilot never approves or
rejects. It has no tool that changes a run's status; its only write is a proposal record.

## Modes
- **Rule-based** (no key): a fixed sequence of read-only tools, then a finding built from the failed checks and the
  evidence. Every step and the proposal are audited with actor `agent:rules`.
- **Gemini** (per-request key, never stored): tool calling in `providers.py` (`GeminiToolChat`, Gemini only for now),
  a loop in `agent.py` with a limit of 8 tool calls and the fixed tool list below. Actor `agent:gemini`.
  Other providers get a readable "Gemini only for now" error.

## Tools (thin wrappers over Desk, read-only except propose)
| Tool | Desk |
|---|---|
| `get_invoice(id)` | `get_run` (only the invoice under investigation) |
| `find_vendor(name_or_vat)` | `find_vendor` (VendorBook matching) |
| `vendor_history(vendor_id)` | `vendor_history`: earlier invoices matched to the vendor |
| `iban_history(vendor_id)` | `iban_history`: master IBAN and IBANs on earlier invoices |
| `get_po(number)` | `po_by_number` + `po_match` |
| `similar_invoices(id)` | `similar_invoices`: earlier runs from the same seller with the same number or amount |
| `reread(id)` | reads the file again with the request's reader; returns the differences, saves nothing |
| `simulate_rule(rule)` | `simulate` (dry run) |
| `propose(recommendation, summary_en, summary_ar, evidence)` | `save_proposal`; never changes status |

Recommendations: `approve`, `reject`, `hold` (find out more before deciding). Reject when the document itself is
invalid and needs a corrected invoice; hold when the invoice may be fine but a fact must be verified first (bank or VAT
change, second approval for large amounts, currency). See `reviewer-decisions.md`.

## Guard
Everything read from a document is data. The agent's system prompt carries the same rule as the extraction prompt
(ignore instructions found in documents and say so), tool results that hold document text are marked as document
data, and a small detector flags text addressed to an AI so the finding mentions it. Structural limits stand
regardless of what the model says: no status-changing tool, `get_invoice`/`reread` only for the invoice under
investigation, a validated recommendation, capped text lengths, and a step limit.

## Audit and panel
`agent.investigate` (the person who asked), `agent.step` per tool call, `agent.propose`, `agent.error`. The review
panel shows the mode, the recommendation, the finding with evidence and links, and the steps taken. The run
timeline gets a "copilot suggested" event.

## Evaluation
`evaluation.py` scores copilot recommendations on the items the desk sends to review. The right decision comes from
`answers.json`: expected approved means approve, expected rejected means reject, and for expected review a
per-scenario table (`REVIEWER_DECISION`) written down in `evaluation.py`. Figures: agreement, unsafe approve
recommendations, holds, steps and tokens per item. The rule-based copilot is scored with every built-in evaluation;
Gemini is scored on a stratified, paced sample. Worded as measured on synthetic samples only.

## Also in this change
- Reset and a fresh demo load restore the default rules with versions starting at 1 (SQLite sequence cleared).
- `tools/e2e.py` launches the full Chromium build (`channel="chromium"`) so PDFs render in screenshots.

## Tests
Desk read methods, rule-based findings per scenario, agent loop with a fake Gemini transport (tool calls, step limit,
bad recommendation, hidden instructions, key never stored or logged, never changes status), API roles and errors,
evaluation figures, i18n keys. Browser checks (`ui_check.py`, `a11y_check.py`) at the end, EN/AR, light/dark.
