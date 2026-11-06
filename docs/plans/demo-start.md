# Demo start: sources, a clean first visit, reset

## Problem
Loading the same samples twice makes every clean invoice a duplicate of itself, and the duplicate rule rejects. On the
shared demo the dashboard turns mostly red. (Today the Evaluation page runs on its own scratch database and adds nothing
to the dashboard; the repeats come from loading samples again.)

## Changes
1. **Source on every run**: `upload` (files and samples sent through intake) or `evaluation`. Old rows tagged `sample`
   become `upload` on start. Evaluation runs are now also recorded in the main database, tagged `evaluation`, so they can
   be inspected; they never enter the review queue or its badge.
2. **Duplicates per source**: the duplicate check only compares runs with the same source.
3. **Dashboard**: a source filter (Uploads, Evaluation, All), default Uploads, and "Top rejection reasons" beside
   "Rules that fail most": the reject-severity checks behind automatic rejections, plus "Rejected by a reviewer".
   `/api/stats?source=` does the filtering.
4. **Settings (admin)**: "Reset demo data" with a confirm step. Clears runs and the audit log, restores the default
   rules and reseeds the vendors and POs (the existing `/api/admin/reset`). The button moves here from Runs.
5. **Welcome card** on the dashboard when nothing has been uploaded: two sentences on the product, "Load sample
   invoices" (`POST /api/samples/demo`: 20 fixed samples, rule-based reader, chosen from the answer key so about half
   approve, a third go to review and the rest reject, mixed formats and languages, no images or unusual wording that
   the built-in reader cannot read) and "Try with your own AI key" (goes to Evaluation).
6. **Demo note** in the app shell when demo mode is on: "Demo with sample data. Resets on restart. Do not upload real
   invoices."

## Tests
Source tagging and migration, per-source duplicates, stats filter and rejection reasons, the demo set's mix and that
loading it gives the expected decisions, evaluation runs kept out of the queue, the new endpoints and roles.
Browser check: welcome card, filter, note and reset, in English and Arabic.
