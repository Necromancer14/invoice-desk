# Right decision for review items (REVIEWER_DECISION)

**Principle.** Reject when the document itself is invalid and needs a corrected invoice. Hold when the invoice may be
fine but a fact must be verified first (vendor bank or VAT change, second approval for large amounts, currency).

The rule-based copilot follows the same principle (`_EFFECT` and the findings in `src/invoice_desk/agent.py`), and so
does the Gemini prompt. A changed IBAN is therefore "hold and verify with the vendor", never "reject".

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
| `clean` | inv-018, inv-026, inv-053 (text and PDF); inv-001 (image) | The total is above 50,000 (the high value rule); inv-001 is an image the built-in reader could not read | approve | A genuine invoice from a known vendor. See point 1 below: this row now disagrees with the large amount rule |
| `qr_mismatch` | inv-006, inv-027 (text), inv-069, inv-092 (PDF), inv-077 (XML); inv-070 (image) | The QR code total differs from the printed total; inv-070 is an unreadable image | reject | Two amounts on one document: the document is invalid. Ask the vendor for a corrected invoice |
| `future_date` | inv-042 | The issue date is in the future | reject | An invoice cannot be issued in the future. The document is invalid; ask for a corrected invoice |
| `hijri_future` | inv-068 | The Hijri issue date converts to a future Gregorian date | reject | Same as above, found through the Hijri conversion |
| `missing_vat` | inv-051 (text), inv-078 (XML) | The seller VAT number is missing | reject | A tax invoice needs the seller's VAT number. The document is incomplete; ask for a corrected invoice |
| `over_limit` | inv-017, inv-021, inv-058 (text and PDF); inv-002 (image) | The total is above 50,000; inv-002 is an unreadable image | hold | The invoice may be fine, but a large amount needs a second approval |
| `non_sar` | inv-016 (PDF), inv-020 (text) | Currency is USD, not SAR, and the total is above 50,000 | hold | The invoice may be fine, but the currency must be confirmed with the vendor, and the amount needs a second approval |
| `iban_changed` | inv-083 (text), inv-084 (XML), inv-090 (PDF) | The bank account differs from the one in the vendor master (marked high risk) | hold | The invoice may be genuine, but a changed bank account is a classic fraud pattern. Verify it with the vendor through a contact you already hold before paying |
| `vendor_vat_mismatch` | inv-087 | The seller VAT number differs from the one in the vendor master | hold | Either the vendor record or the invoice is out of date. Verify with the vendor before paying |
| `due_before_issue` | inv-012 | The due date is before the issue date | hold | Probably a typing error in one date; check with the vendor rather than send the whole invoice back |
| `unknown_vendor` | inv-086 | The seller is not in the vendor master | hold | Not wrong on its face. Someone has to find out who the seller is and add them, then decide |
| `po_over` | inv-088, inv-089 | The total is above its purchase order | hold | Might be a fault or a legitimate change of scope. Ask the buyer whether the order should change |

## What changed in this version

`over_limit`, `non_sar`, `iban_changed`, `vendor_vat_mismatch` and `due_before_issue` moved to hold. The copilot's own
findings moved with them: a changed IBAN, a differing VAT number, a due date before the issue date, a large amount and a
foreign currency all suggest hold now. The copilot never suggests approve while any of them applies.

## Points to check when you review

1. **`clean` against the large amount rule.** Three `clean` samples (inv-018, inv-026, inv-053) went to review only
   because their total is above 50,000. The table says approve, but the principle says a large amount needs a second
   approval, so the copilot holds them and is scored wrong on all three. Either those samples move to hold, or the
   copilot approves large amounts from known vendors. I left the `clean` row as asked.
2. **Images.** Three rows include images the built-in reader cannot read at all (inv-001, inv-002, inv-070), and
   inv-051 is a text file read with low confidence. The right decision for those depends on what is on the page, which
   the answer key knows and the rule-based copilot cannot see, so it says "hold". Gemini can read the file again, so it
   may do better there.
3. **Missing VAT number.** Reject here means "send it back for a corrected invoice", not "refuse the vendor".
4. **Approve is rare.** With these rules the rule-based copilot suggests approve only when no check that matters failed
   and the vendor is confirmed, which does not happen among the 41 review items. That is why no approve suggestion is
   counted as unsafe.
