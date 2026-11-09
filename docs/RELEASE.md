# Release: invoice-desk v2

Everything on `dev` that is not yet on `main` (`40572aa`, "Docs: test counts, the browser checks, and the fixes
outcome"). 30 commits, no breaking API change, no database migration needed: a fresh or reset database gets the new
tables and the sample vendors and purchase orders; an existing database keeps its own rules and vendors.

## What is new since main

**Checks against ZATCA e-invoicing fields**
- Hijri dates (1420 to 1500 AH) read and converted with the Umm al-Qura calendar.
- Zero-rated, exempt and out-of-scope lines carry no VAT; the VAT check uses only the standard-rated amount.
- SAR is assumed when no currency is printed, with a note.
- UBL 2.1 XML invoices are read directly, with no AI; XML with a DOCTYPE or ENTITY is refused. In review and run detail an
  XML invoice is shown as an invoice (parties, lines, totals, IBAN, PO, QR code), with the source XML behind a toggle.
- QR codes are read from images and PDF pages, not only from printed text, and compared with the invoice.
- 18 new synthetic samples for these checks.

**Vendor master and purchase orders**
- A Vendors page: list, add, edit, delete, CSV import for vendors and POs.
- Name matching across English and Arabic, with "Link to vendor" from review.
- Five new rules: vendor known, vendor not blocked, VAT number matches, IBAN matches (marked high risk), within the PO.
- IBAN shape and mod-97 check digits. No bank verification and no live lookup.
- 11 new synthetic samples.

**Demo start**
- An empty dashboard offers "Load sample invoices" (20 samples) or "Try with your own AI key".
- Runs carry their source (upload or evaluation); the duplicate check compares within a source; evaluation runs
  never reach the review queue.
- Admins reset the demo from Settings, after a confirm step.

**Portal redesign**
- One design token set, solid surfaces instead of frosted glass, IBM Plex Sans and IBM Plex Sans Arabic served
  from the app, tabular figures, one status palette.
- Run detail and review: the original beside the reasons and fields, failed checks first, high risk on top, a
  decision bar that stays on screen, keyboard shortcuts shown beside it.
- Review queue as a dense two-line list; dashboard with a headline figure and a fixed daily chart; sortable runs
  table; Rules, Vendors, Evaluation, Settings, Upload and Audit log on the same tokens.
- Before and after screenshots in `docs/ui/`, with notes in `docs/ui/README.md`.

**Arabic**
- The reasons under failed checks and the vendor match explanation are shown in Arabic, from templates kept in
  `web/src/reasons.ts`. A test fails when the server writes a sentence no template covers.

**Docs and tests**
- README: Gemini 3.1 Flash Lite and rule-based results, labelled as synthetic regression figures; a table of what
  is and is not checked; fresh screenshots in English and Arabic.
- 304 tests. Browser checks (`tools/ui_check.py`) and axe-core accessibility checks
  (`tools/a11y_check.py`) pass in English and Arabic, light and dark.

## Steps to publish

Run these from the main checkout (`C:\Users\Maaz.Mahmood\projects\invoice-desk`), which has `dev` checked out.

1. Confirm `dev` is clean and has the release:
   ```bash
   git status
   git log --oneline -1 dev
   ```
2. Run the gate once more:
   ```bash
   py -m pytest -q
   npm --prefix web run typecheck
   npm --prefix web run build
   node tools/check_i18n.mjs
   ```
   `npm run build` must leave `git status` clean; if it changes `web/dist`, commit that first.
3. Merge into `main` and push (main has nothing `dev` lacks, so this is a fast-forward):
   ```bash
   git checkout main
   git merge --ff-only dev
   git push origin main
   ```
   If you prefer a pull request, push `dev` instead (`git push origin dev`) and open a PR from `dev` to `main` on
   GitHub, then merge it there.
4. On GitHub, open the **Actions** tab and wait for the `ci` run on `main` to go green (backend tests, i18n
   check, portal build).
5. The demo at https://invoice-desk-ct8w.onrender.com is set up in the Render dashboard, not in this repository.
   If the service deploys automatically from `main`, a deploy starts after the push; otherwise open the service in
   Render and press **Manual Deploy**, then **Deploy latest commit**. The build uses the `Dockerfile`.
6. Smoke test the live demo once the deploy finishes (the first load can take about a minute on the free tier):
   - pick Admin, press **Load sample invoices**, and check the dashboard shows 20 invoices;
   - open the review queue and approve one with `a`;
   - switch to Arabic and check the review screen mirrors and the reasons are in Arabic.
7. Go back to `dev` for further work:
   ```bash
   git checkout dev
   ```

Nothing in `launch/` is committed (it is in `.gitignore`); the demo video, thumbnails and post text live there
locally.
