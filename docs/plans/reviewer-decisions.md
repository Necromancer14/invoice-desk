# Right decision for review items (REVIEWER_DECISION)

The copilot evaluation needs a "right decision" for every invoice the built-in reader sends to review. `answers.json`
only says "needs review", so `REVIEWER_DECISION` in `src/invoice_desk/evaluation.py` holds our judgement for each kind
of problem. It is a judgement, not a fact: change a row there and the evaluation figures change with it.

Samples the answer key expects approved count as **approve**, and samples it expects rejected count as **reject**. Only
the scenarios below, where the key expects review, use this table. A scenario missing from the table counts as **hold**.

Scoring: a suggestion is right when it equals the decision below. A suggestion to approve where the decision is not
approve is counted as unsafe. A "hold" never counts as unsafe, but counts as wrong where the decision is approve or
reject.

| Scenario | Invoices expected in review | Why the rules sent it to review | Decision | Reason |
|---|---|---|---|---|
| `clean` | inv-018, inv-026, inv-053 (text and PDF); inv-001 (image) | The total is above 50,000 (the high value rule); inv-001 is an image the built-in reader could not read | approve | A genuine invoice from a known vendor; the rule only asks for a second look at a large amount. See the note on images below |
| `over_limit` | inv-017, inv-021, inv-058 (text and PDF); inv-002 (image) | The total is above 50,000; inv-002 is an unreadable image | approve | Same as above: size alone is not a fault, and a person confirms the amount |
| `non_sar` | inv-016 (PDF), inv-020 (text) | Currency is USD, not SAR, and the total is above 50,000 | approve | A foreign currency invoice is allowed when the vendor trades in that currency; both are above the limit too, so a person confirms the amount |
| `iban_changed` | inv-083 (text), inv-084 (XML), inv-090 (PDF) | The bank account differs from the one in the vendor master (marked high risk) | reject | A changed bank account is the classic payment fraud pattern. Do not pay until the vendor confirms the change by a contact already held |
| `qr_mismatch` | inv-006, inv-027 (text), inv-069, inv-092 (PDF), inv-077 (XML); inv-070 (image) | The QR code total differs from the printed total; inv-070 is an unreadable image | reject | Two amounts on one invoice: one of them is wrong. Ask the vendor for a corrected invoice |
| `due_before_issue` | inv-012 | The due date is before the issue date | reject | The dates cannot both be right. Ask for a corrected invoice |
| `future_date` | inv-042 | The issue date is in the future | reject | An invoice cannot be issued in the future. Ask for a corrected invoice |
| `hijri_future` | inv-068 | The Hijri issue date converts to a future Gregorian date | reject | Same as above, found through the Hijri conversion |
| `missing_vat` | inv-051 (text), inv-078 (XML) | The seller VAT number is missing | reject | A tax invoice needs the seller's VAT number, so it cannot be accepted as it stands. Ask for a corrected invoice |
| `vendor_vat_mismatch` | inv-087 | The seller VAT number differs from the one in the vendor master | reject | Either the vendor or the number is wrong. Ask the vendor before paying |
| `unknown_vendor` | inv-086 | The seller is not in the vendor master | hold | Not wrong on its face. Someone has to find out who the seller is and add them, then decide |
| `po_over` | inv-088, inv-089 | The total is above its purchase order | hold | Might be a fault or a legitimate change of scope. Ask the buyer whether the order should change |

## Points to check when you review

1. **Images.** Three rows include images the built-in reader cannot read at all (inv-001, inv-002, inv-070), and
   inv-051 is a text file read with low confidence. The right decision for those depends on what is on the
   page, which the answer key knows and the rule-based copilot cannot see, so it says "hold" and is counted wrong.
   Gemini can read the file again, so it should do better there. If you would rather not score the rule-based copilot on
   images it cannot read, the alternative is to leave unreadable images out of the copilot figures. It does not change
   any decision above.
2. **High value approve.** Approving a 300,000 SAR invoice on the strength of "known vendor, nothing else failed" is the
   boldest row. The copilot only suggests, and the high value rule still sends every such invoice to a person, but you
   may prefer `hold` for the very large ones (inv-017 at about 318,000 and inv-021 at about 306,000, inv-058 at about
   253,000).
3. **Missing VAT number.** Reject here means "send it back", not "refuse the vendor". If you prefer hold, change `missing_vat`
   in `REVIEWER_DECISION`.
4. **Unknown vendor and PO over** are the only holds, so they are also where a "hold" suggestion is scored as right.
