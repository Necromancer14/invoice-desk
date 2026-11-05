"""FastAPI app. Roles: viewer reads, reviewer uploads and decides, admin edits rules and settings."""
from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .auth import Auth, AuthError, allows
from .db import dumps, loads
from .desk import Desk, DeskError
from .evaluation import ai_history, evaluate, evaluate_ai, evaluated_ids, save_ai_rows
from .providers import ProviderError, build_extractor, public_providers
from .rules import HELP_FUNCS, RULE_TYPES
from .samples import list_samples, sample_bytes
from .schema import FIELDS

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
RECORDED = Path(__file__).resolve().parents[2] / "data" / "recorded"


class RateLimiter:
    def __init__(self, limit: int, window: float = 60.0):
        self.limit, self.window, self.hits, self.lock = limit, window, defaultdict(deque), threading.Lock()

    def check(self, key: str) -> None:
        now = time.time()
        with self.lock:
            q = self.hits[key]
            while q and q[0] < now - self.window:
                q.popleft()
            if len(q) >= self.limit:
                raise HTTPException(429, "too many requests, slow down a little")
            q.append(now)


SAMPLE_TEXT = "TAX INVOICE\nInvoice No: T-1\nIssue Date: 2026-10-01\nSeller: Test Co\nSeller VAT No: 300000000000003\nCurrency: SAR\nSubtotal: 1,000.00 SAR\nVAT (15%): 150.00 SAR\nTotal (including VAT): 1,150.00 SAR\n"


class Review(BaseModel):
    decision: str
    note: str = ""
    edits: dict = {}


class RuleIn(BaseModel):
    key: str = ""
    name: str
    type: str
    params: dict = {}
    severity: str
    enabled: bool = True
    message: str = ""
    note: str = ""


def llm_from(request: Request) -> dict | None:
    """The browser sends its AI choice per request. Nothing here is stored."""
    h = request.headers
    if not h.get("x-llm-provider"):
        return None
    return dict(provider=h.get("x-llm-provider", ""), key=h.get("x-llm-key", ""), model=h.get("x-llm-model", ""))


def _int(body: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        v = int(body.get(key, default))
    except (TypeError, ValueError):
        raise HTTPException(400, f"{key} must be a whole number") from None
    if not lo <= v <= hi:
        raise HTTPException(400, f"{key} must be between {lo} and {hi}")
    return v


def create_app(desk: Desk | None = None, auth: Auth | None = None, rate_limit: int = 40, eval_transport=None) -> FastAPI:
    """eval_transport: an httpx transport for the AI evaluation's provider calls (tests use a fake one)."""
    desk = desk or Desk(os.environ.get("INVOICE_DESK_DB", ":memory:"))
    auth = auth or Auth()
    limiter = RateLimiter(rate_limit)
    app = FastAPI(title="invoice-desk", version=__version__,
                  description="Saudi e-invoice intake: extraction, rules-as-data validation, human review, audit.")
    app.state.desk, app.state.auth = desk, auth
    jobs: dict[str, dict] = {}

    def need(role: str):
        def dep(authorization: str | None = Header(default=None)):
            try:
                user = auth.verify((authorization or "").removeprefix("Bearer ").strip() or None)
            except AuthError as exc:
                raise HTTPException(401, str(exc)) from exc
            if not allows(user["role"], role):
                raise HTTPException(403, f"needs the {role} role")
            return user
        return dep

    @app.exception_handler(DeskError)
    async def _desk_error(_: Request, exc: DeskError):
        return JSONResponse({"detail": str(exc)}, status_code=exc.status)

    # ---------------------------------------------------------------- session
    @app.get("/api/health")
    def health():
        return dict(ok=True, version=__version__, demo=auth.demo)

    @app.post("/api/auth/demo")
    def demo_login(body: dict):
        try:
            role = body.get("role", "")
            return dict(token=auth.demo_login(role), role=role, name=f"demo-{role}")
        except AuthError as exc:
            raise HTTPException(403, str(exc)) from exc

    @app.post("/api/auth/login")
    def login(body: dict):
        limiter.check("login")
        try:
            token = auth.login(body.get("name", ""), body.get("password", ""))
        except AuthError as exc:
            raise HTTPException(401, str(exc)) from exc
        user = auth.verify(token)
        return dict(token=token, role=user["role"], name=user["sub"])

    @app.get("/api/auth/me")
    def me(user=Depends(need("viewer"))):
        return dict(name=user["sub"], role=user["role"])

    # ------------------------------------------------------------------- runs
    @app.post("/api/runs")
    async def submit(request: Request, files: list[UploadFile] = File(...), mode: str = Form(default=""),
                     user=Depends(need("reviewer"))):
        llm = llm_from(request)
        limiter.check(request.client.host if request.client else "local")
        if len(files) > 20:
            raise HTTPException(400, "at most 20 files per upload")
        ids = []
        for f in files:
            blob = await f.read()
            ids.append(desk.submit(f.filename or "invoice", blob, f.content_type, user["sub"], mode or None, llm))
        return dict(ids=ids)

    @app.get("/api/runs")
    def runs(status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0, user=Depends(need("viewer"))):
        return desk.list_runs(status, q, limit, offset)

    @app.get("/api/runs/{rid}")
    def run(rid: int, user=Depends(need("viewer"))):
        return desk.get_run(rid)

    @app.get("/api/runs/{rid}/file")
    def run_file(rid: int, user=Depends(need("viewer"))):
        blob, ctype, name = desk.get_blob(rid)
        return Response(blob, media_type=ctype, headers={"Content-Disposition": f'inline; filename="{name}"',
                                                         "X-Content-Type-Options": "nosniff"})

    @app.post("/api/runs/{rid}/review")
    def review(rid: int, body: Review, user=Depends(need("reviewer"))):
        return desk.review(rid, body.decision, user["sub"], body.edits, body.note)

    @app.post("/api/runs/{rid}/reprocess")
    def reprocess(rid: int, request: Request, user=Depends(need("reviewer"))):
        desk.reprocess(rid, user["sub"], llm_from(request))
        return dict(ok=True)

    @app.get("/api/review/next")
    def review_next(user=Depends(need("viewer"))):
        return desk.next_review() or {}

    @app.get("/api/review/queue")
    def review_queue(user=Depends(need("viewer"))):
        return desk.review_queue()

    @app.get("/api/stats")
    def stats(user=Depends(need("viewer"))):
        return desk.stats()

    # ------------------------------------------------------------------ rules
    @app.get("/api/rules")
    def rules(user=Depends(need("viewer"))):
        return dict(rules=desk.rules(), version=desk.rules_version())

    @app.get("/api/rules/types")
    def rule_types(user=Depends(need("viewer"))):
        types = {k: {kk: vv for kk, vv in v.items() if kk != "fn"} for k, v in RULE_TYPES.items()}
        return dict(types=types, fields=FIELDS, functions=HELP_FUNCS)

    @app.post("/api/rules")
    def rule_save(body: RuleIn, user=Depends(need("admin"))):
        d = body.model_dump()
        return desk.upsert_rule(d, user["sub"], d.pop("note", ""))

    @app.put("/api/rules/reorder")
    def rule_reorder(body: dict, user=Depends(need("admin"))):
        return dict(version=desk.reorder_rules(body.get("keys", []), user["sub"]))

    @app.delete("/api/rules/{key}")
    def rule_delete(key: str, user=Depends(need("admin"))):
        return dict(version=desk.delete_rule(key, user["sub"]))

    @app.post("/api/rules/simulate")
    def rule_simulate(body: dict, user=Depends(need("admin"))):
        return desk.simulate(candidate=body.get("rules"), rule=body.get("rule"))

    @app.get("/api/rules/versions")
    def versions(user=Depends(need("viewer"))):
        return desk.rule_versions()

    @app.get("/api/rules/versions/{version}")
    def version_detail(version: int, user=Depends(need("viewer"))):
        return desk.version_rules(version)

    @app.post("/api/rules/rollback")
    def rollback(body: dict, user=Depends(need("admin"))):
        return dict(version=desk.rollback(int(body.get("version", 0)), user["sub"]))

    # --------------------------------------------------- settings, audit, misc
    @app.get("/api/settings")
    def get_settings(user=Depends(need("viewer"))):
        return desk.settings()

    @app.put("/api/settings")
    def put_settings(body: dict, user=Depends(need("admin"))):
        return desk.update_settings(body, user["sub"])

    @app.get("/api/audit")
    def audit(limit: int = 200, actor: str | None = None, action: str | None = None, user=Depends(need("viewer"))):
        return desk.audit_log(limit, actor, action)

    @app.get("/api/export.csv")
    def export(user=Depends(need("viewer"))):
        return Response(desk.export_csv(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=approved-invoices.csv"})

    @app.post("/api/admin/reset")
    def reset(body: dict | None = None, user=Depends(need("admin"))):
        desk.reset(user["sub"], keep_rules=bool((body or {}).get("keep_rules")))
        return dict(ok=True)

    @app.get("/api/samples")
    def samples(user=Depends(need("viewer"))):
        return list_samples()

    @app.post("/api/samples/submit")
    def samples_submit(body: dict, request: Request, mode: str | None = None,
                       user=Depends(need("reviewer"))):
        llm = llm_from(request)
        limiter.check(request.client.host if request.client else "local")
        files = body.get("files", [])[:60]
        known = {s["file"]: s for s in list_samples()}
        ids = []
        for name in files:
            if name not in known:
                raise HTTPException(404, f"unknown sample {name}")
            ids.append(desk.submit(name, sample_bytes(name), None, user["sub"], body.get("mode") or mode, llm, source="sample"))
        return dict(ids=ids)

    @app.get("/api/samples/{name}")
    def sample_file(name: str, user=Depends(need("viewer"))):
        try:
            blob = sample_bytes(name)
        except FileNotFoundError:
            raise HTTPException(404, "no such sample") from None
        from .extractors import guess_type
        return Response(blob, media_type=guess_type(name, None))

    # ------------------------------------------------------------- evaluation
    def _run_eval_ai(job_id: str, llm: dict, opts: dict):
        job = jobs[job_id]
        try:
            model = build_extractor(llm).model
            skip = evaluated_ids(desk.db, llm["provider"], model) if opts["only_new"] else []
            res = evaluate_ai(llm, desk.rules(), sample_size=opts["sample_size"], seed=opts["seed"], rpm=opts["rpm"],
                              skip_ids=skip, transport=eval_transport, progress=job.update)
            version = desk.rules_version()
            save_ai_rows(desk.db, res["provider"], res["model"], version, res["rows"])
            last = {k: res[k] for k in ("provider", "model", "seed", "sample_size", "attempted", "evaluated", "errors", "stopped")}
            last.update(picked=len(res["picked"]), rpm=opts["rpm"], only_new=opts["only_new"], skipped=len(skip),
                        rules_version=version, ran_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        error_rows=[r for r in res["rows"] if r["outcome"] == "error"])
            desk.db.run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        ("eval_ai_last", dumps(last)))
            job.update(status="done", stopped=res["stopped"], evaluated=res["evaluated"], errors=res["errors"], total=len(res["picked"]))
        except Exception as exc:
            job.update(status="error", error=f"{type(exc).__name__}: {exc}")

    def _run_eval(job_id: str, mode: str, llm: dict | None):
        try:
            res = evaluate(mode=mode, llm=llm, rules=desk.rules())
            res["provider"] = (llm or {}).get("provider")
            res["rules_version"] = desk.rules_version()
            res["ran_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            desk.db.run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (f"eval_{mode}", dumps(res)))
            jobs[job_id] = dict(status="done", mode=mode)
        except Exception as exc:
            jobs[job_id] = dict(status="error", error=f"{type(exc).__name__}: {exc}", mode=mode)

    @app.post("/api/evaluation/run")
    def eval_run(body: dict, request: Request, user=Depends(need("admin"))):
        """mode=rules: all 60 samples with the built-in reader.
        mode=ai: sample_size (1-60, default 20) picked by seed, paced at rpm requests a minute (default 4),
        only_new skips samples already scored with this model."""
        mode = body.get("mode", "rules")
        llm = llm_from(request)
        if mode == "ai":
            try:
                build_extractor(llm or {})
            except ProviderError as exc:
                raise HTTPException(400, str(exc)) from exc
            if any(j.get("status") == "running" and j.get("mode") == "ai" for j in jobs.values()):
                raise HTTPException(409, "an AI evaluation is already running")
            opts = dict(sample_size=_int(body, "sample_size", 20, 1, 60), rpm=_int(body, "rpm", 4, 1, 60),
                        seed=_int(body, "seed", 1, 0, 1_000_000), only_new=bool(body.get("only_new")))
        elif mode != "rules":
            raise HTTPException(400, "mode must be rules or ai")
        job = f"job{len(jobs) + 1}"
        jobs[job] = dict(status="running", mode=mode)
        desk.audit(user["sub"], "evaluation.run", mode if mode == "rules" else f"ai {llm['provider']} n={opts['sample_size']} rpm={opts['rpm']}")
        if mode == "ai":
            threading.Thread(target=_run_eval_ai, args=(job, llm, opts), daemon=True).start()
        else:
            threading.Thread(target=_run_eval, args=(job, mode, llm), daemon=True).start()
        return dict(job=job)

    @app.get("/api/evaluation/jobs/{job}")
    def eval_job(job: str, user=Depends(need("viewer"))):
        return jobs.get(job) or {"status": "unknown"}

    @app.get("/api/evaluation")
    def eval_results(user=Depends(need("viewer"))):
        row = desk.db.one("SELECT value FROM settings WHERE key='eval_rules'")
        last = desk.db.one("SELECT value FROM settings WHERE key='eval_ai_last'")
        out = dict(rules=loads(row["value"]) if row else None, ai_models=ai_history(desk.db),
                   ai_last=loads(last["value"]) if last else None)
        recorded = RECORDED / "evaluation_ai.json"
        out["recorded_ai"] = loads(recorded.read_text(encoding="utf-8")) if recorded.exists() else None
        return out

    # ------------------------------------------------------------ AI providers
    @app.get("/api/llm/providers")
    def providers(user=Depends(need("viewer"))):
        return public_providers()

    @app.post("/api/llm/test")
    def llm_test(request: Request, user=Depends(need("reviewer"))):
        limiter.check("llmtest:" + (request.client.host if request.client else "local"))
        llm = llm_from(request)
        try:
            ext = build_extractor(llm or {}).extract(SAMPLE_TEXT.encode(), "text/plain", "test.txt")
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"could not reach the provider: {type(exc).__name__}") from exc
        ok = ext.fields.get("total") == 1150.0
        return dict(ok=ok, latency_ms=ext.latency_ms, model=ext.model,
                    message="Connected and read the test invoice correctly." if ok else "Connected, but the test invoice was not read as expected. Try another model.")

    # --------------------------------------------------------------- frontend
    if WEB_DIST.is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "not found")
            f = (WEB_DIST / path).resolve()
            if path and WEB_DIST.resolve() in f.parents and f.is_file():
                return FileResponse(f)
            return FileResponse(WEB_DIST / "index.html")

    return app


app = create_app() if os.environ.get("INVOICE_DESK_AUTOCREATE", "1") == "1" else None
