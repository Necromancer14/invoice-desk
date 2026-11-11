# Release: invoice-desk v3

Everything on `dev` that is not yet on `main` (`cc9ad80`, "Merge pull request #1 from Necromancer14/dev"). 21 commits, no
breaking API change, no database migration needed: a fresh or reset database gets the new `proposals` table and the
default rules at version 1; an existing database keeps its own rules and vendors. This replaces the v2 notes, which
shipped in the earlier merge (the readable XML view, the ZATCA checks, vendors and POs and the portal redesign are
already on `main`).

## What is new since main

**Review copilot** (plan: `docs/plans/review-copilot.md`)
- An **Investigate** button on each invoice in review. It looks up the vendor, the vendor's earlier invoices and IBANs,
  the purchase order and similar earlier invoices, then suggests approve, reject or find out more, with its reasons and
  the steps it took. It only suggests: it has no tool that approves or rejects, and a person decides.
- **Rule-based mode**, no key needed. **Gemini mode**: tool calling for Google Gemini only, at most 10 read-only tool calls
  per invoice plus a `propose` call that writes a proposal and never changes a status. The key arrives per request and
  is never stored or logged. Default model `gemini-3.1-flash-lite`; the Model box stays editable.
- One principle for both modes: reject when the document itself is invalid and needs a corrected invoice; hold when
  the invoice may be fine but a fact must be verified first (a changed bank account or VAT number, a large amount, a
  foreign currency). A changed IBAN is hold and verify, never reject (`docs/plans/reviewer-decisions.md`).
- The summary is always a suggestion ("I suggest ..."), in English and Arabic. The finding has **Reasons** (failed checks
  and facts that directly support the suggestion) and **Context** (weaker facts), each item with a small source label,
  never a tool name.
- Every step is in the audit log as `agent:rules` or `agent:gemini`, shown in the panel, and in the run timeline.

**`run_checks` guard: code judges, the model explains**
- The model never judges dates, amounts or VAT arithmetic. A `run_checks` tool runs the full rule set in code, on the
  re-read fields after a re-read, and the agent must call it after any re-read.
- A reason that names a check that did not fail, names none, or calls a date or an amount wrong without a failed check
  behind it is dropped (not moved to Context) and noted in the steps. A reject with no surviving reason becomes a hold.
- The prompt carries today's date (server clock, Asia/Riyadh), but the checks still decide. This fixes a real Gemini
  run that called a past issue date "in the future".

**Copilot evaluation**
- The Evaluation page scores the copilot against the answer key: agreement on the items it could read, the deferral
  rate, and unsafe approve suggestions, worded as measured on synthetic samples only. Gemini can be run on a paced
  sample with your key.
- **Deferrals**: a suggestion to find out more because the file could not be read (or was read with low confidence) is
  counted as deferred, not wrong. For Gemini it is deferred only if the file was still unreadable after its own re-read.
- The right decision for each kind of problem is our judgement, listed in `docs/plans/reviewer-decisions.md`. On the
  41 review items in the built-in reader's results, the rule-based copilot deferred 16, agreed with the right decision on
  all 25 it could read, and made no unsafe approve suggestion. These figures say nothing about real invoices.

**Dashboard v2**
- A greeting with what needs a person, figures for today or the last 7, 30 or 90 days with the change against the
  period before, SAR totals for approved, waiting and rejected (other currencies are counted, not converted), a chart of
  invoices per day by outcome, the oldest invoices waiting, and an activity feed.

**Run timeline**
- Run detail shows what happened to an invoice in plain words: received, read by which reader, checked with which rules
  version, routed, what people did (and the copilot's suggestion), from the audit log.

**Demo history**
- The sample loader dates 54 more invoices over the last 30 days, with decisions by two made-up reviewers, so the
  charts and the activity feed have something to show. The welcome set (20) is unchanged: 11 approved, 6 in review,
  3 rejected. All synthetic, labelled in the demo note.
- Reset demo data and a fresh demo load restore the default rules with version numbering starting again at 1.

**Licence change**
- `LICENSE` is now "all rights reserved; published for viewing and evaluation only" and replaces the MIT text. Copies
  obtained earlier under MIT keep that grant; new versions fall under the new terms.

**Tests and tooling**
- 391 tests. Browser checks (`tools/ui_check.py`) and axe-core checks (`tools/a11y_check.py`) cover the copilot panel and
  the new Evaluation figures in English and Arabic.
- `Desk` takes an optional clock and each event uses one timestamp, which removed a flaky test.
- `tools/e2e.py` launches the full Chromium build so PDFs render in README screenshots.

## Steps to publish

Run these from the main checkout (`C:\Users\Maaz.Mahmood\projects\invoice-desk`), which has `dev` checked out.

1. Confirm `dev` is clean and has the release:
   ```bash
   git status
   git log --oneline -1 dev
   ```
2. Run the gate once more, with nothing listening on port 8000:
   ```bash
   py -m pytest -q
   npm --prefix web run typecheck
   node tools/check_i18n.mjs
   npm --prefix web run build
   py -m uvicorn invoice_desk.api:app --port 8000   # in another terminal, then:
   py tools/ui_check.py
   ```
   `npm run build` must leave `git status` clean; if it changes `web/dist`, commit that first.
3. Merge into `main` and push (main has nothing `dev` lacks, so this is a fast-forward):
   ```bash
   git checkout main
   git merge --ff-only dev
   git push origin main
   git checkout dev
   ```
   If you prefer a pull request, push `dev` instead (`git push origin dev`) and open a PR from `dev` to `main` on
   GitHub, then merge it there.
4. On GitHub, open the **Actions** tab and wait for the `ci` run on `main` to go green (backend tests, i18n
   check, portal build).
5. The demo at https://invoice-desk-ct8w.onrender.com is set up in the Render dashboard, not in this repository.
   If the service deploys automatically from `main`, a deploy starts after the push; otherwise open the service in
   Render and press **Manual Deploy**, then **Deploy latest commit**. The build uses the `Dockerfile`.
6. Smoke test the live demo once the deploy finishes (the first load can take about a minute on the free tier):
   - reset demo data, press **Load sample invoices**, and check the welcome set gives 11 approved, 6 in review and
     3 rejected;
   - open the review queue, press **Investigate** on one item and check a suggestion with reasons and steps appears;
   - switch to Arabic and check the review screen mirrors and the panel is in Arabic.
   Do not run Gemini on the live demo unless you mean to: it uses a key and sends invoices to the provider.

Nothing in `launch/` is committed (it is in `.gitignore`); the demo video, thumbnails and post text live there
locally.
