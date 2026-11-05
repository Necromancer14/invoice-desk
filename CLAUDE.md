# CLAUDE.md

Guidance for working in this repository. See `README.md` for the product overview and `docs/` for deploy, demo and Windows walk-throughs.

## What this is

invoice-desk is a Saudi e-invoice intake desk. A FastAPI backend reads invoices (text, PDF, image), validates the extracted fields with a rule engine whose rules live in SQLite, auto-approves, routes to human review or rejects, and logs everything. A React + TypeScript portal (`web/`) is built to `web/dist` and served by the same FastAPI app.

## Project layout

```
src/invoice_desk/        Python package (installed from src/ via pyproject.toml)
  api.py                 FastAPI app: create_app(), routes under /api, role checks, rate limiter,
                         serves web/dist as the SPA. Module-level `app` is what uvicorn loads.
  desk.py                Service layer (no HTTP): submit/process pipeline, review, versioned rules,
                         simulate (dry run), stats, audit, CSV export, reset.
  rules.py               14 rule types (RULE_TYPES), safe custom-expression evaluator (AST allowlist),
                         run_rules() and decide().
  default_rules.py       Rule set seeded into a fresh database.
  extractors.py          RuleBasedExtractor (no key needed), ClaudeExtractor, prompts, PDF text.
  providers.py           Gemini / Groq / OpenRouter / Ollama / OpenAI adapters; build_extractor().
  schema.py              Field names (FIELDS, REQUIRED, NUMERIC) and the JSON schema for AI extraction.
  db.py                  Thin SQLite wrapper and table schema.
  auth.py                HMAC-signed tokens; roles viewer < reviewer < admin; demo login.
  evaluation.py          Scores reader + rules against data/samples/answers.json.
  samples.py             Lists/serves the bundled sample invoices.
  qr.py                  ZATCA-style TLV QR encode/decode.  textnorm.py: Arabic digits, numbers, dates.
  mcp_server.py          MCP server (stdio) exposing read/check tools.
tests/                   pytest suite; conftest.py sets INVOICE_DESK_AUTOCREATE=0 and provides
                         `desk` (in-memory, sync, fixed today=2026-11-05), `auth`, `good` fixtures.
web/                     Portal source: src/App.tsx, src/views/*.tsx, src/api.ts, src/i18n.ts (EN/AR).
web/dist/                Built portal, committed so Node is not needed to run the app.
data/samples/            60 synthetic invoices + answers.json (generated, do not hand-edit).
tools/generate_data.py   Regenerates data/samples (needs qrcode, reportlab, playwright+chromium).
tools/e2e.py             Playwright walk-through against a running server; rewrites docs/screens/*.png.
Dockerfile, docker-compose.yml   Multi-stage build (Node builds portal, Python serves on port 7860).
.github/workflows/ci.yml         CI: `pytest -q` on Python 3.12, and `npm ci && npm run build` in web/.
```

Key design points:
- Keep HTTP concerns in `api.py` and business logic in `desk.py`.
- Rules are data: any rule change goes through `Desk.upsert_rule`/`delete_rule`/`reorder_rules`/`rollback`, each of which snapshots a new rule version.
- The AI key arrives per request in `X-LLM-Provider` / `X-LLM-Key` / `X-LLM-Model` headers and must never be stored or logged (tests check this).
- If an AI call fails, processing falls back to the rule-based reader.

## Running the tests

Requires Python 3.11+. On Windows use the `py` launcher:

```bash
py -m pip install -e ".[dev,mcp]"
py -m pytest
```

- `py -m pytest -q` for quiet output; `py -m pytest tests/test_rules.py -k vat` to narrow.
- pytest config lives in `pyproject.toml` (`pythonpath = ["src"]`, `testpaths = ["tests"]`).
- `tests/test_mcp.py` is skipped unless the `mcp` extra is installed.
- Provider tests use fake HTTP transports; no network or API keys are needed.
- Evaluation from the command line: `py -m invoice_desk.evaluation`.

## Running the server

```bash
py -m pip install -e .
py -m uvicorn invoice_desk.api:app --port 8000
```

Open http://localhost:8000 and pick a role (demo mode). API docs are at `/docs`.

Environment variables:
- `INVOICE_DESK_DB`: SQLite path; default `:memory:` (data resets on restart).
- `DEMO_MODE`: `1` (default) lets visitors pick a role; `0` requires real sign-in.
- `INVOICE_DESK_USERS`: `name:password:role,...` for real sign-in.
- `INVOICE_DESK_SECRET`: token signing secret (random per process if unset).
- `INVOICE_DESK_ALLOW_LOCAL=1`: enables the Ollama (local model) provider.
- `INVOICE_DESK_AUTOCREATE=0`: skip building the module-level `app` (used by tests).

Docker: `docker compose up --build`, then open http://localhost:7860.

MCP server: `py -m invoice_desk.mcp_server` (needs the `mcp` extra).

## Rebuilding the web portal

Needs Node (CI uses Node 22).

```bash
cd web
npm ci
npm run build
```

- `npm run build` runs `tsc --noEmit` and then `vite build`, writing to `web/dist/`. The FastAPI app serves `web/dist` directly, so restart or refresh the server after a build. Commit the updated `web/dist` because the app ships with the built portal.
- `npm run typecheck` runs only the TypeScript check.
- Dev mode with hot reload: run the API on port 8000, then `npm run dev` in `web/`. Vite proxies `/api` to `http://127.0.0.1:8000`.
- The portal uses no UI or chart library; keep it that way (bundle is about 62 KB gzipped). Fonts are in `web/public/fonts`.
