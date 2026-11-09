# Check reasons in Arabic

## Problem

In Arabic the portal translates every label, but the reason under a failed check ("VAT is 140.00 but 15% of
1000.00 is 150.00") and the vendor match explanation are shown in English, exactly as the server wrote them. These
are the lines a reviewer reads most.

## Approach (portal only, no API change)

The server builds these sentences from a small, fixed set of templates in `rules.py`, `vendors.py` and
`default_rules.py`. The portal lists the same templates in `web/src/serverText.ts` with `tk()`, so
`tools/check_i18n.mjs` insists on an Arabic entry for each, and translates a detail line like this:

1. Match the whole line against the templates, in order, as anchored patterns (`{x}` becomes a lazy group).
2. A rule's message wraps the detail as `message (detail)`: translate both halves and join them with the
   `{message} ({detail})` template.
3. A line that joins several problems with `"; "` is split, each part translated, and joined with the Arabic
   semicolon.
4. Anything that still does not match (a message an admin typed, a future template) is shown as sent.

Captured values are filled back in as follows: field ids (`issue_date`) through the field labels, comma lists of
field ids one by one, "English name" and the like through the existing labels, a nested IBAN problem through the
templates again, and every other value (numbers, names, codes, dates) inside first-strong isolates so it keeps its
own direction inside the Arabic sentence. English output is unchanged.

Applied to the check reasons in `CheckList` and to the vendor match explanation in `VendorPanel`.

## Tests

- `tests/test_reasons.py` reads the templates out of `serverText.ts`, runs the bundled samples and hand-made
  invoices that reach every rule branch and every IBAN problem through the rules, and asserts each fail or skip
  detail and each vendor explanation is fully covered by the templates (the same algorithm, in Python). A new
  server sentence without a template fails the suite.
- `check_i18n.mjs` checks every template has Arabic with the same placeholders.
- `tools/ui_check.py` gains a check that in Arabic the reasons in the review queue are in Arabic.
