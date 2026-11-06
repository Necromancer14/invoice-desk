"""The service layer: intake, pipeline, review, rules admin, stats, audit. No HTTP in here."""
from __future__ import annotations

import csv
import io
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from .db import DB, dumps, loads
from .default_rules import DEFAULT_RULES
from .extractors import Extraction, NeedsVision, RuleBasedExtractor, guess_type
from .providers import ProviderError, build_extractor
from .rules import RULE_TYPES, Ctx, decide, run_rules, validate_rule
from .schema import FIELDS, NUMERIC, SCALARS, empty_fields
from .textnorm import number_key, parse_date, to_number, vat_key

MAX_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = {"text/plain", "application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"}
FINAL = {"approved", "rejected", "approved_human", "rejected_human", "failed"}
# How long free text may be. Long enough for real use, short enough that nobody can fill the database through a form.
MAX_RULE_NAME, MAX_RULE_MESSAGE, MAX_VERSION_NOTE, MAX_REVIEW_NOTE = 120, 300, 500, 2000
PDF_UNREADABLE = "This PDF could not be opened. It may be damaged or not really a PDF."
DEFAULT_SETTINGS = {"default_mode": "rules", "price_in_per_mtok": "",
                    "price_out_per_mtok": "", "auto_approve": "true"}


def clean_filename(name: str | None) -> str:
    """The last part of an uploaded file's name, without control characters, at most 120 characters."""
    name = re.sub(r"[\x00-\x1f\x7f]", "", str(name or "")).replace("\\", "/").split("/")[-1].strip()
    return name[:120] or "invoice.txt"


_MAGIC = {"application/pdf": (b"%PDF",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/jpeg": (b"\xff\xd8\xff",),
          "image/gif": (b"GIF87a", b"GIF89a")}
_KIND = {"application/pdf": "a PDF", "image/png": "a PNG image", "image/jpeg": "a JPEG image", "image/gif": "a GIF image",
         "image/webp": "a WebP image", "text/plain": "a text file"}


def content_matches(ctype: str, blob: bytes) -> bool:
    """Do the first bytes fit the type the file claims? Stops, say, a program renamed to .txt or .png."""
    head = blob[:1024]
    if ctype in _MAGIC:
        return any(head.lstrip().startswith(m) if ctype == "application/pdf" else head.startswith(m) for m in _MAGIC[ctype])
    if ctype == "image/webp":
        return head[:4] == b"RIFF" and head[8:12] == b"WEBP"
    if ctype == "text/plain":
        return b"\x00" not in blob[:8192]
    return False


def friendly_error(exc: Exception) -> str:
    """What a person sees when processing fails. The technical detail stays in the trace."""
    if type(exc).__module__.split(".")[0] == "pypdf":
        return PDF_UNREADABLE
    return f"{type(exc).__name__}: {exc}"[:300]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeskError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class Desk:
    def __init__(self, db_path: str = ":memory:", today: date | None = None, sync: bool = False, workers: int = 2,
                 extractor_factory=None):
        self.db = DB(db_path)
        self.today = today
        self.sync = sync
        self.pool = None if sync else ThreadPoolExecutor(max_workers=workers)
        self.extractor_factory = extractor_factory or self._default_factory
        if not self.db.one("SELECT key FROM rules LIMIT 1"):
            self._seed_rules()

    # ---------------------------------------------------------------- helpers
    def _today(self) -> date:
        return self.today or date.today()

    def audit(self, actor: str, action: str, target: str = "", detail: str = "") -> None:
        self.db.run("INSERT INTO audit(ts,actor,action,target,detail) VALUES(?,?,?,?,?)", (now(), actor, action, target, detail))

    def _default_factory(self, mode: str, llm: dict | None):
        if mode == "ai":
            try:
                return build_extractor(llm or {})
            except ProviderError as exc:
                raise DeskError(str(exc), 400) from exc
        return RuleBasedExtractor()

    # --------------------------------------------------------------- settings
    def settings(self) -> dict:
        out = dict(DEFAULT_SETTINGS)
        out.update({r["key"]: r["value"] for r in self.db.all("SELECT key,value FROM settings")})
        return out

    def update_settings(self, changes: dict, actor: str) -> dict:
        for k, v in changes.items():
            if k not in DEFAULT_SETTINGS:
                raise DeskError(f"unknown setting {k}")
            v = str(v).strip()
            if k == "default_mode" and v not in ("rules", "ai"):
                raise DeskError("default_mode must be rules or ai")
            if k == "auto_approve" and v not in ("true", "false"):
                raise DeskError("auto_approve must be true or false")
            if k.startswith("price_") and v != "":
                try:
                    float(v)
                except ValueError:
                    raise DeskError(f"{k} must be a number") from None
            self.db.run("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        self.audit(actor, "settings.update", "", ", ".join(changes))
        return self.settings()

    # ------------------------------------------------------------------ rules
    @staticmethod
    def _rule_row(r: dict) -> dict:
        return dict(key=r["key"], name=r["name"], type=r["type"], params=loads(r["params"], {}), severity=r["severity"],
                    enabled=bool(r["enabled"]), message=r["message"] or "", position=r["position"])

    def rules(self) -> list[dict]:
        return [self._rule_row(r) for r in self.db.all("SELECT * FROM rules ORDER BY position, key")]

    def rules_version(self) -> int:
        r = self.db.one("SELECT MAX(version) v FROM rule_versions")
        return (r or {}).get("v") or 0

    def _save_rules(self, rules: list[dict]) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM rules")
            for i, r in enumerate(rules):
                self.db.conn.execute("INSERT INTO rules VALUES(?,?,?,?,?,?,?,?)",
                                     (r["key"], i, r["name"], r["type"], dumps(r.get("params") or {}), r["severity"],
                                      1 if r.get("enabled", True) else 0, r.get("message", "")))
            self.db.conn.commit()

    def _snapshot(self, author: str, note: str) -> int:
        cur = self.db.run("INSERT INTO rule_versions(snapshot,author,note,created_at) VALUES(?,?,?,?)",
                          (dumps(self.rules()), author, note, now()))
        return cur.lastrowid

    def _seed_rules(self) -> None:
        self._save_rules([dict(r, enabled=True) for r in DEFAULT_RULES])
        self._snapshot("system", "Default rule set")

    def rule_versions(self) -> list[dict]:
        rows = self.db.all("SELECT version,author,note,created_at,snapshot FROM rule_versions ORDER BY version DESC")
        return [dict(version=r["version"], author=r["author"], note=r["note"], created_at=r["created_at"],
                     rule_count=len(loads(r["snapshot"], []))) for r in rows]

    @staticmethod
    def _slug(name: str) -> str:
        s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return s[:40] or "rule"

    def _clean_rule(self, rule: dict) -> dict:
        r = dict(key=(rule.get("key") or "").strip(), name=(rule.get("name") or "").strip(), type=rule.get("type"),
                 params=rule.get("params") or {}, severity=rule.get("severity"), enabled=bool(rule.get("enabled", True)),
                 message=(rule.get("message") or "").strip())
        if len(r["name"]) > MAX_RULE_NAME:
            raise DeskError(f"a rule name can be at most {MAX_RULE_NAME} characters")
        if len(r["message"]) > MAX_RULE_MESSAGE:
            raise DeskError(f"the message can be at most {MAX_RULE_MESSAGE} characters")
        if not isinstance(r["params"], dict):
            raise DeskError("params must be an object")
        try:
            validate_rule(r)
        except ValueError as exc:
            raise DeskError(str(exc)) from exc
        return r

    def upsert_rule(self, rule: dict, actor: str, note: str = "") -> dict:
        r = self._clean_rule(rule)
        note = (note or "").strip()
        if len(note) > MAX_VERSION_NOTE:
            raise DeskError(f"the note can be at most {MAX_VERSION_NOTE} characters")
        current = self.rules()
        keys = {x["key"] for x in current}
        if not r["key"]:
            base = self._slug(r["name"])
            r["key"], n = base, 2
            while r["key"] in keys:
                r["key"], n = f"{base}-{n}", n + 1
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", r["key"]):
            raise DeskError("key may only contain lowercase letters, digits and dashes")
        exists = r["key"] in keys
        updated = [r if x["key"] == r["key"] else x for x in current] if exists else current + [r]
        self._save_rules(updated)
        v = self._snapshot(actor, note or f"{'Edited' if exists else 'Added'} {r['name']}")
        self.audit(actor, "rule.update" if exists else "rule.create", r["key"], r["name"])
        return dict(rule=r, version=v)

    def delete_rule(self, key: str, actor: str) -> int:
        current = self.rules()
        if key not in {x["key"] for x in current}:
            raise DeskError("rule not found", 404)
        self._save_rules([x for x in current if x["key"] != key])
        v = self._snapshot(actor, f"Deleted {key}")
        self.audit(actor, "rule.delete", key)
        return v

    def reorder_rules(self, keys: list[str], actor: str) -> int:
        current = {x["key"]: x for x in self.rules()}
        if set(keys) != set(current):
            raise DeskError("reorder needs every rule key exactly once")
        self._save_rules([current[k] for k in keys])
        v = self._snapshot(actor, "Reordered rules")
        self.audit(actor, "rule.reorder")
        return v

    def rollback(self, version: int, actor: str) -> int:
        row = self.db.one("SELECT snapshot FROM rule_versions WHERE version=?", (version,))
        if not row:
            raise DeskError("version not found", 404)
        self._save_rules(loads(row["snapshot"], []))
        v = self._snapshot(actor, f"Rolled back to version {version}")
        self.audit(actor, "rule.rollback", str(version))
        return v

    def version_rules(self, version: int) -> list[dict]:
        row = self.db.one("SELECT snapshot FROM rule_versions WHERE version=?", (version,))
        if not row:
            raise DeskError("version not found", 404)
        return loads(row["snapshot"], [])

    def _dup_checker(self, run_id: int | None):
        def check(vat: str, number: str) -> bool:
            # compared after normalising: Arabic-Indic digits, spaces, letter case
            want = (vat_key(vat), number_key(number))
            if not all(want):
                return False
            rows = self.db.all("SELECT fields, final_fields FROM runs WHERE (? IS NULL OR id < ?) AND status NOT IN "
                               "('rejected','rejected_human','failed','queued')", (run_id, run_id))
            for r in rows:
                f = loads(r["final_fields"]) or loads(r["fields"], {}) or {}
                if (vat_key(f.get("seller_vat")), number_key(f.get("invoice_number"))) == want:
                    return True
            return False
        return check

    def _ctx(self, run_id: int | None, confidence: float) -> Ctx:
        return Ctx(today=self._today(), confidence=confidence, is_duplicate=self._dup_checker(run_id))

    def simulate(self, candidate: list[dict] | None = None, limit: int = 300, rule: dict | None = None) -> dict:
        """Dry run: what would change if these rules had been in force for past runs? Nothing is written."""
        current = self.rules()
        if candidate is None:
            if rule is None:
                raise DeskError("send a rule or a full rule list")
            r = self._clean_rule(rule)
            candidate = [r if x["key"] == r["key"] else x for x in current]
            if r["key"] not in {x["key"] for x in current}:
                candidate = current + [r]
        else:
            candidate = [self._clean_rule(x) for x in candidate]
        rows = self.db.all("SELECT id,filename,fields,final_fields,extraction FROM runs WHERE fields IS NOT NULL "
                           "ORDER BY id DESC LIMIT ?", (limit,))
        changed, same = [], 0
        for r in rows:
            f = loads(r["final_fields"]) or loads(r["fields"], {})
            conf = (loads(r["extraction"], {}) or {}).get("confidence", 1.0)
            ctx = self._ctx(r["id"], conf)
            before, after = decide(run_rules(current, f, ctx)), decide(run_rules(candidate, f, ctx))
            if before != after:
                changed.append(dict(id=r["id"], filename=r["filename"], before=before, after=after))
            else:
                same += 1
        return dict(checked=len(rows), unchanged=same, changed=changed[:100], changed_count=len(changed),
                    shift=dict(Counter(f"{c['before']} -> {c['after']}" for c in changed)))

    # ----------------------------------------------------------------- intake
    def submit(self, filename: str, blob: bytes, content_type: str | None, actor: str, mode: str | None = None,
               llm: dict | None = None, source: str = "upload") -> int:
        filename = clean_filename(filename)
        ctype = guess_type(filename, content_type)
        if ctype not in ALLOWED_TYPES:
            raise DeskError(f"unsupported file type {ctype}", 415)
        if not blob:
            raise DeskError("empty file")
        if len(blob) > MAX_BYTES:
            raise DeskError("file is larger than 5 MB", 413)
        if not content_matches(ctype, blob):
            raise DeskError(f"{filename} does not look like {_KIND.get(ctype, ctype)}", 415)
        mode = mode or self.settings()["default_mode"]
        if mode not in ("rules", "ai"):
            raise DeskError("mode must be rules or ai")
        if mode == "ai":
            if not (llm and llm.get("provider")):
                raise DeskError("choose an AI provider and add its key in Settings")
            if self.extractor_factory == self._default_factory:
                self._default_factory("ai", llm)  # fails early with a readable message
        t = now()
        cur = self.db.run("INSERT INTO runs(filename,content_type,blob,source,size,status,mode,created_at,updated_at,submitted_by,trace)"
                          " VALUES(?,?,?,?,?,?,?,?,?,?,?)", (filename, ctype, blob, source, len(blob), "queued", mode, t, t, actor, "[]"))
        rid = cur.lastrowid
        self.audit(actor, "run.submit", str(rid), f"{filename} ({mode})")
        if self.sync:
            self.process(rid, llm)
        else:
            self.pool.submit(self.process, rid, llm)
        return rid

    def _step(self, trace: list, name: str, t0: float, detail: str = "", ok: bool = True) -> None:
        trace.append(dict(step=name, ms=int((time.time() - t0) * 1000), ok=ok, detail=detail, at=now()))

    def process(self, rid: int, llm: dict | None = None) -> None:
        row = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not row:
            return
        trace: list = [dict(step="ingest", ms=0, ok=True, detail=f"{row['filename']} · {row['size']} bytes · {row['content_type']}", at=row["created_at"])]
        self.db.run("UPDATE runs SET status='processing', updated_at=? WHERE id=?", (now(), rid))
        s = self.settings()
        try:
            t0 = time.time()
            ext = None
            notes: list = []
            try:
                extractor = self.extractor_factory(row["mode"], llm)
                ext = extractor.extract(row["blob"], row["content_type"], row["filename"])
                self._step(trace, "extract", t0, f"{ext.extractor} · confidence {ext.confidence}")
            except NeedsVision as exc:
                ext = Extraction(empty_fields(), 0.0, {}, [f"Could not read automatically: {exc}. Switch to an AI model or key it in."], "rule-based")
                self._step(trace, "extract", t0, str(exc), ok=False)
            except DeskError:
                raise
            except Exception as exc:
                if row["mode"] != "ai":
                    raise
                self._step(trace, "extract", t0, f"AI call failed ({str(exc)[:140] or type(exc).__name__}); falling back to rule-based", ok=False)
                notes.append("The AI call failed, so the built-in reader was used instead")
                try:
                    ext = RuleBasedExtractor().extract(row["blob"], row["content_type"], row["filename"])
                except NeedsVision as nv:
                    ext = Extraction(empty_fields(), 0.0, {}, [f"Could not read automatically: {nv}"], "rule-based")
            ext.notes = list(ext.notes or []) + notes
            fields = {k: ext.fields.get(k) for k in FIELDS}
            t1 = time.time()
            results = run_rules(self.rules(), fields, self._ctx(rid, ext.confidence))
            decision = decide(results)
            fails = [x["name"] for x in results if x["status"] == "fail"]
            self._step(trace, "validate", t1, f"{len(results)} rules, {len(fails)} failed" + (f": {', '.join(fails)}" if fails else ""))
            if decision == "approved" and s["auto_approve"] == "false":
                decision = "needs_review"
                self._step(trace, "route", time.time(), "auto-approve is switched off, sent to review")
            else:
                self._step(trace, "route", time.time(), {"approved": "auto-approved", "needs_review": "sent to human review", "rejected": "rejected automatically"}[decision])
            meta = dict(confidence=ext.confidence, field_confidence=ext.field_confidence, notes=ext.notes, extractor=ext.extractor,
                        model=ext.model, tokens_in=ext.tokens_in, tokens_out=ext.tokens_out, latency_ms=ext.latency_ms)
            self.db.run("UPDATE runs SET status=?, fields=?, extraction=?, results=?, rules_version=?, trace=?, updated_at=?, "
                        "decided_at=? WHERE id=?",
                        (decision, dumps(fields), dumps(meta), dumps(results), self.rules_version(), dumps(trace), now(),
                         now() if decision != "needs_review" else None, rid))
            self.audit("system", "run.decision", str(rid), decision)
        except Exception as exc:
            self._step(trace, "error", time.time(), f"{type(exc).__name__}: {exc}"[:300], ok=False)
            self.db.run("UPDATE runs SET status='failed', error=?, trace=?, updated_at=?, decided_at=? WHERE id=?",
                        (friendly_error(exc), dumps(trace), now(), now(), rid))
            self.audit("system", "run.failed", str(rid), str(exc)[:200])

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _current_fields(r: dict) -> dict | None:
        """The reviewer's corrected fields when there are any, otherwise what the reader extracted."""
        return loads(r["final_fields"]) or loads(r["fields"])

    def _run_view(self, r: dict, full: bool = False) -> dict:
        ex = loads(r["extraction"], {}) or {}
        out = dict(id=r["id"], filename=r["filename"], content_type=r["content_type"], size=r["size"], source=r["source"],
                   status=r["status"], mode=r["mode"], created_at=r["created_at"], updated_at=r["updated_at"],
                   decided_at=r["decided_at"], decision_by=r["decision_by"], submitted_by=r["submitted_by"],
                   edited=bool(r["edited"]), error=r["error"], rules_version=r["rules_version"],
                   confidence=ex.get("confidence"), extractor=ex.get("extractor"),
                   fields=self._current_fields(r))
        if out["fields"]:
            out["summary"] = {k: out["fields"].get(k) for k in ("invoice_number", "seller_name", "total", "currency")}
        if full:
            results = loads(r["results"], [])
            out.update(extracted=loads(r["fields"]), final_fields=loads(r["final_fields"]), extraction=ex, results=results,
                       trace=loads(r["trace"], []), decision_note=r["decision_note"])
        return out

    def get_run(self, rid: int) -> dict:
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        return self._run_view(r, True)

    def get_blob(self, rid: int) -> tuple[bytes, str, str]:
        r = self.db.one("SELECT blob,content_type,filename FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        return r["blob"], r["content_type"], r["filename"]

    def list_runs(self, status: str | None = None, q: str | None = None, limit: int = 50, offset: int = 0) -> dict:
        where, args = [], []
        if status:
            where.append("status IN (%s)" % ",".join("?" * len(status.split(","))))
            args += status.split(",")
        if q:
            where.append("(filename LIKE ? OR fields LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
        w = ("WHERE " + " AND ".join(where)) if where else ""
        total = self.db.one(f"SELECT COUNT(*) n FROM runs {w}", args)["n"]
        cols = "id,filename,content_type,size,source,status,mode,created_at,updated_at,decided_at,decision_by,submitted_by,edited,error,rules_version,extraction,fields,final_fields"
        rows = self.db.all(f"SELECT {cols} FROM runs {w} ORDER BY id DESC LIMIT ? OFFSET ?", args + [min(limit, 200), offset])
        return dict(total=total, items=[self._run_view(r) for r in rows])

    def next_review(self, after_id: int | None = None) -> dict | None:
        r = self.db.one("SELECT * FROM runs WHERE status='needs_review' ORDER BY id LIMIT 1")
        return self._run_view(r, True) if r else None

    def review_queue(self) -> list[dict]:
        """Every run waiting for a person, oldest first, without blobs or traces: enough to draw a list."""
        rows = self.db.all("SELECT id,filename,created_at,fields,final_fields,results FROM runs "
                           "WHERE status='needs_review' ORDER BY id")
        out = []
        for r in rows:
            f = self._current_fields(r) or {}
            results = loads(r["results"], [])
            out.append(dict(id=r["id"], filename=r["filename"], created_at=r["created_at"], seller=f.get("seller_name"),
                            invoice_number=f.get("invoice_number"), total=f.get("total"), currency=f.get("currency"),
                            failed_checks=sum(1 for x in results if x["status"] == "fail" and x["severity"] == "review")))
        return out

    # ----------------------------------------------------------------- review
    def review(self, rid: int, decision: str, actor: str, edits: dict | None = None, note: str = "") -> dict:
        r = self.db.one("SELECT * FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        if r["status"] != "needs_review":
            raise DeskError(f"run is {r['status']}, only runs waiting for review can be decided", 409)
        if decision not in ("approve", "reject"):
            raise DeskError("decision must be approve or reject")
        if decision == "reject" and not (note or "").strip():
            raise DeskError("add a note explaining the rejection")
        if len(note or "") > MAX_REVIEW_NOTE:
            raise DeskError(f"the note can be at most {MAX_REVIEW_NOTE} characters")
        fields = loads(r["fields"], empty_fields())
        final = dict(fields)
        changed = []
        for k, v in (edits or {}).items():
            if k not in FIELDS:
                raise DeskError(f"unknown field {k}")
            if k in NUMERIC:
                v = to_number(v) if v not in (None, "") else None
                if v is None and edits[k] not in (None, ""):
                    raise DeskError(f"{k} must be a number")
            elif k in ("issue_date", "due_date") and v:
                v = parse_date(v)
                if not v:
                    raise DeskError(f"{k} is not a valid date")
            elif k != "line_items":
                v = (str(v).strip() or None) if v is not None else None
            if final.get(k) != v:
                changed.append(k)
                final[k] = v
        conf = (loads(r["extraction"], {}) or {}).get("confidence", 1.0)
        results = run_rules(self.rules(), final, self._ctx(rid, 1.0 if changed else conf))
        trace = loads(r["trace"], [])
        trace.append(dict(step="human review", ms=0, ok=True, at=now(),
                          detail=f"{actor} chose {decision}" + (f", corrected {', '.join(changed)}" if changed else "")))
        status = "approved_human" if decision == "approve" else "rejected_human"
        self.db.run("UPDATE runs SET status=?, final_fields=?, results=?, edited=?, decision_by=?, decision_note=?, decided_at=?, "
                    "updated_at=?, trace=? WHERE id=?",
                    (status, dumps(final), dumps(results), 1 if changed else 0, actor, note, now(), now(), dumps(trace), rid))
        self.audit(actor, f"review.{decision}", str(rid), (note or "") + (f" [edited: {', '.join(changed)}]" if changed else ""))
        return self.get_run(rid)

    def reprocess(self, rid: int, actor: str, llm: dict | None = None) -> None:
        r = self.db.one("SELECT status, mode FROM runs WHERE id=?", (rid,))
        if not r:
            raise DeskError("run not found", 404)
        if r["status"] in ("processing", "queued"):
            raise DeskError("run is still processing", 409)
        if r["mode"] == "ai" and not (llm and llm.get("provider")):
            raise DeskError("choose an AI provider and add its key in Settings")
        self.db.run("UPDATE runs SET status='queued', final_fields=NULL, edited=0, decision_by=NULL, decision_note=NULL WHERE id=?", (rid,))
        self.audit(actor, "run.reprocess", str(rid))
        if self.sync:
            self.process(rid, llm)
        else:
            self.pool.submit(self.process, rid, llm)

    # ------------------------------------------------------------------ stats
    def stats(self) -> dict:
        rows = self.db.all("SELECT id,status,mode,created_at,decided_at,results,extraction,edited FROM runs")
        by_status = Counter(r["status"] for r in rows)
        s = self.settings()
        tin = tout = 0
        latencies, ttr = [], []
        failing: Counter = Counter()
        days = Counter()
        for r in rows:
            ex = loads(r["extraction"], {}) or {}
            tin += ex.get("tokens_in", 0) or 0
            tout += ex.get("tokens_out", 0) or 0
            if ex.get("latency_ms"):
                latencies.append(ex["latency_ms"])
            for x in loads(r["results"], []) or []:
                if x["status"] == "fail":
                    failing[x["name"]] += 1
            days[r["created_at"][:10]] += 1
            if r["status"] in ("approved_human", "rejected_human") and r["decided_at"]:
                ttr.append((datetime.fromisoformat(r["decided_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds())
        machine_done = sum(by_status[k] for k in ("approved", "rejected", "needs_review", "approved_human", "rejected_human"))
        end = date.today()
        series = [dict(day=(end - timedelta(days=i)).isoformat(), count=days.get((end - timedelta(days=i)).isoformat(), 0)) for i in range(13, -1, -1)]
        cost = None
        if s["price_in_per_mtok"] != "" and s["price_out_per_mtok"] != "":
            cost = round(tin / 1e6 * float(s["price_in_per_mtok"]) + tout / 1e6 * float(s["price_out_per_mtok"]), 4)
        return dict(total=len(rows), by_status={k: by_status.get(k, 0) for k in
                                                ("approved", "needs_review", "rejected", "approved_human", "rejected_human", "failed", "queued", "processing")},
                    review_queue=by_status["needs_review"],
                    auto_approve_rate=round(by_status["approved"] / machine_done, 3) if machine_done else None,
                    human_corrected=sum(1 for r in rows if r["edited"]),
                    avg_extract_ms=int(sum(latencies) / len(latencies)) if latencies else None,
                    avg_time_to_review_s=int(sum(ttr) / len(ttr)) if ttr else None,
                    tokens_in=tin, tokens_out=tout, cost=cost, ai_runs=sum(1 for r in rows if r["mode"] == "ai"),
                    top_failing=[dict(rule=k, count=v) for k, v in failing.most_common(6)], series=series,
                    rules_version=self.rules_version())

    def audit_log(self, limit: int = 200, actor: str | None = None, action: str | None = None) -> list[dict]:
        where, args = [], []
        if actor:
            where.append("actor=?")
            args.append(actor)
        if action:
            where.append("action LIKE ?")
            args.append(action + "%")
        w = ("WHERE " + " AND ".join(where)) if where else ""
        return self.db.all(f"SELECT * FROM audit {w} ORDER BY id DESC LIMIT ?", args + [min(limit, 1000)])

    # ----------------------------------------------------------------- export
    def export_csv(self) -> str:
        buf = io.StringIO()
        w = csv.writer(buf)
        cols = ["id", "filename", "status", "invoice_number", "issue_date", "seller_name", "seller_vat", "buyer_name", "currency",
                "subtotal", "vat_amount", "total", "confidence", "decision_by", "created_at", "decided_at"]
        w.writerow(cols)
        for r in self.db.all("SELECT * FROM runs ORDER BY id"):
            if r["status"] not in ("approved", "approved_human"):
                continue
            f = loads(r["final_fields"]) or loads(r["fields"], {}) or {}
            ex = loads(r["extraction"], {}) or {}
            row = dict(id=r["id"], filename=r["filename"], status=r["status"], confidence=ex.get("confidence"),
                       decision_by=r["decision_by"] or "auto", created_at=r["created_at"], decided_at=r["decided_at"])
            w.writerow([row.get(c, f.get(c)) for c in cols])
        return buf.getvalue()

    # ------------------------------------------------------------------ reset
    def reset(self, actor: str, keep_rules: bool = False) -> None:
        with self.db.lock:
            self.db.conn.execute("DELETE FROM runs")
            self.db.conn.execute("DELETE FROM audit")
            if not keep_rules:
                self.db.conn.execute("DELETE FROM rules")
                self.db.conn.execute("DELETE FROM rule_versions")
            self.db.conn.commit()
        if not keep_rules:
            self._seed_rules()
        self.audit(actor, "demo.reset")

    def wait_idle(self, timeout: float = 30) -> None:
        t0 = time.time()
        while time.time() - t0 < timeout:
            if not self.db.one("SELECT id FROM runs WHERE status IN ('queued','processing') LIMIT 1"):
                return
            time.sleep(0.05)
