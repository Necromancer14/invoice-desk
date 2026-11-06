"""Scores a reader + the current rules against the answer key. Runs on a throwaway in-memory desk.

Two modes:
  rules  every sample through the built-in reader, in one go (free, fast).
  ai     a stratified sample through an AI model, paced for free-tier limits, with no fallback to the built-in
         reader: a failed AI call is recorded as an error and left out of the accuracy figures. Results are
         stored per provider and model so a run can be continued another day and the totals accumulate.
"""
from __future__ import annotations

import json
import random
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from .db import DB, dumps, loads
from .desk import Desk
from .extractors import Extraction, NeedsVision, guess_type
from .providers import DailyQuotaReached, RateLimited, RetryPolicy, build_extractor
from .schema import NUMERIC, SCALARS, empty_fields
from .textnorm import to_number

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "samples"
AUTO = {"approved"}


def load_answers(root: Path = SAMPLES) -> dict:
    return json.loads((root / "answers.json").read_text(encoding="utf-8"))


def _same(field: str, truth, got, alt=None) -> bool:
    if alt and field in alt and str(got or "").strip() == alt[field]:
        return True
    if truth in (None, "") and got in (None, ""):
        return True
    if field in NUMERIC:
        a, b = to_number(truth), to_number(got)
        return a is not None and b is not None and abs(a - b) < 0.011
    return str(truth or "").strip().lower() == str(got or "").strip().lower()


def _score(it: dict, run: dict) -> dict:
    """One sample's result: the decision against the answer key and how many fields were read right."""
    got = run.get("extracted") or {}
    fields = {k: _same(k, it["truth"].get(k), got.get(k), it.get("alt_names")) for k in SCALARS}
    return dict(id=it["id"], file=it["file"], format=it["format"], lang=it["lang"], scenario=it["scenario"], outcome="ok",
                expected=it["expected_status"], got=run["status"], agree=run["status"] == it["expected_status"],
                fields_ok=sum(fields.values()), fields_total=len(SCALARS), field_hits=fields, confidence=run.get("confidence"),
                unsafe=run["status"] in AUTO and it["expected_status"] not in AUTO,
                false_reject=run["status"] == "rejected" and it["expected_status"] != "rejected")


def summarize_rows(rows: list[dict]) -> dict:
    """Accuracy figures over scored rows. Error rows are counted but never enter a percentage."""
    ok = [r for r in rows if r.get("outcome", "ok") == "ok"]
    n = len(ok)
    field_total = sum(r["fields_total"] for r in ok)
    by_field: dict[str, list[int]] = {k: [0, 0] for k in SCALARS}
    for r in ok:
        for k, hit in (r.get("field_hits") or {}).items():
            if k in by_field:
                by_field[k][0] += bool(hit)
                by_field[k][1] += 1

    def slice_(key):
        out: dict[str, dict] = {}
        for r in ok:
            b = out.setdefault(r[key], dict(n=0, agree=0, fields_ok=0, fields_total=0))
            b["n"] += 1
            b["agree"] += r["agree"]
            b["fields_ok"] += r["fields_ok"]
            b["fields_total"] += r["fields_total"]
        return out
    return dict(count=n, errors=len(rows) - n, fields_total=field_total,
                field_accuracy=round(sum(r["fields_ok"] for r in ok) / field_total, 4) if field_total else None,
                decision_agreement=round(sum(r["agree"] for r in ok) / n, 4) if n else None,
                auto_approve_rate=round(sum(r["got"] in AUTO for r in ok) / n, 4) if n else None,
                review_rate=round(sum(r["got"] == "needs_review" for r in ok) / n, 4) if n else None,
                unsafe_auto_approvals=sum(r["unsafe"] for r in ok), false_rejections=sum(r["false_reject"] for r in ok),
                by_field={k: round(a / b, 3) for k, (a, b) in by_field.items() if b},
                by_format=slice_("format"), by_lang=slice_("lang"), by_scenario=slice_("scenario"))


def _desk(data: dict, rules: list[dict] | None, extractor_factory=None) -> Desk:
    desk = Desk(":memory:", today=date.fromisoformat(data["as_of"]), sync=True, extractor_factory=extractor_factory)
    desk.settings()
    if rules is not None:
        desk._save_rules(rules)
    return desk


def evaluate(mode: str = "rules", llm: dict | None = None, rules: list[dict] | None = None, root: Path = SAMPLES,
             extractor_factory=None, only_text: bool = False, limit: int | None = None) -> dict:
    """Every sample, in file order, through the desk's normal pipeline. Used for the built-in reader."""
    data = load_answers(root)
    items = data["invoices"]
    if only_text:
        items = [i for i in items if i["format"] != "png"]
    if limit:
        items = items[:limit]
    desk = _desk(data, rules, extractor_factory)
    ids = {}
    for it in items:
        blob = (root / it["file"]).read_bytes()
        ids[it["id"]] = desk.submit(it["file"], blob, guess_type(it["file"], None), "evaluation", mode=mode, llm=llm, source="evaluation")
    per = [_score(it, desk.get_run(ids[it["id"]])) for it in items]
    stats = desk.stats()
    out = summarize_rows(per)
    out.update(mode=mode, as_of=data["as_of"], tokens_in=stats["tokens_in"], tokens_out=stats["tokens_out"], rows=per)
    return out


# ------------------------------------------------------------------------------------------- sampling
def stratified_pick(items: list[dict], n: int, seed: int = 1) -> list[dict]:
    """n samples that still look like the whole set, the same ones every time for the same seed.

    First one of everything that matters (the prompt-injection sample, every file type, language and defect
    type, duplicates included), then the remaining places shared out by file type in proportion to the full set.
    """
    pool = sorted(items, key=lambda i: i["id"])
    if n >= len(pool):
        return pool
    if n <= 0:
        return []
    shuffled = pool[:]
    random.Random(seed).shuffle(shuffled)
    chosen: list[dict] = []
    picked = set()

    def take(it):
        chosen.append(it)
        picked.add(it["id"])

    def new_coverage(it):
        return sum(not any(c[k] == it[k] for c in chosen) for k in ("format", "lang", "scenario"))

    targets = [("scenario", "prompt_injection")]
    targets += [("format", v) for v in sorted({i["format"] for i in pool})]
    targets += [("lang", v) for v in sorted({i["lang"] for i in pool})]
    targets += [("scenario", v) for v in sorted({i["scenario"] for i in pool}) if v != "clean"]
    for key, val in targets:
        if len(chosen) >= n:
            break
        if any(c[key] == val for c in chosen):
            continue
        cands = [i for i in shuffled if i["id"] not in picked and i[key] == val]
        if cands:
            take(max(cands, key=new_coverage))  # ties go to the earliest in seed order, so this stays deterministic

    # share the rest out by file type, largest remainder first
    groups: dict[str, list[dict]] = {}
    for it in pool:
        groups.setdefault(it["format"], []).append(it)
    exact = {f: n * len(g) / len(pool) for f, g in groups.items()}
    quota = {f: int(x) for f, x in exact.items()}
    for f in sorted(exact, key=lambda f: (-(exact[f] - quota[f]), f))[: n - sum(quota.values())]:
        quota[f] += 1
    # within a file type, each next place goes to whatever is furthest below its share of the full set:
    # clean versus defective, and language. Covering every defect type above already over-weights defects.
    share = {}
    for key in ("clean", "lang"):
        vals = [(i["scenario"] == "clean") if key == "clean" else i["lang"] for i in pool]
        share[key] = {v: vals.count(v) / len(pool) for v in set(vals)}

    def shortfall(it):
        clean = it["scenario"] == "clean"
        return (n * share["clean"][clean] - sum((c["scenario"] == "clean") == clean for c in chosen)
                + n * share["lang"][it["lang"]] - sum(c["lang"] == it["lang"] for c in chosen))

    for f in sorted(groups):
        while len(chosen) < n and sum(c["format"] == f for c in chosen) < quota[f]:
            cands = [i for i in shuffled if i["id"] not in picked and i["format"] == f]
            if not cands:
                break
            take(max(cands, key=shortfall))
    for it in shuffled:  # coverage can push a file type over its share; top up from whatever is left
        if len(chosen) >= n:
            break
        if it["id"] not in picked:
            take(it)
    return sorted(chosen, key=lambda i: i["id"])


def _duplicate_source(it: dict, items: list[dict]) -> dict | None:
    t = it["truth"]
    return next((s for s in sorted(items, key=lambda s: s["id"]) if s["id"] < it["id"] and s["scenario"] != "duplicate"
                 and s["truth"].get("seller_vat") == t.get("seller_vat") and s["truth"].get("invoice_number") == t.get("invoice_number")), None)


def _add_history(desk: Desk, src: dict) -> None:
    """Record an invoice as already received, from the answer key: the duplicate rule needs it, and it costs no AI call."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    desk.db.run("INSERT INTO runs(filename,content_type,blob,source,size,status,mode,fields,created_at,updated_at,submitted_by,trace)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (src["file"], "text/plain", b"", "history", 0, "approved", "rules", dumps(src["truth"]), now, now, "evaluation", "[]"))


class _Replay:
    """Hands the desk an extraction that was already made, so the normal rules and routing run on it unchanged."""
    def __init__(self):
        self.next: Extraction | None = None

    def extract(self, blob, content_type, filename=""):
        ext, self.next = self.next, None
        return ext


def evaluate_ai(llm: dict, rules: list[dict] | None = None, *, sample_size: int = 20, seed: int = 1, rpm: float = 4,
                skip_ids=(), root: Path = SAMPLES, extractor=None, transport=None, sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.monotonic, progress: Callable[[dict], None] | None = None) -> dict:
    """Run a stratified sample through the AI model in llm, at most rpm requests a minute.

    Never falls back to the built-in reader. A call that still fails after the retries is an "error" row.
    A daily-quota answer or a rate limit that outlasts the retries stops the run; what was done is kept.
    """
    data = load_answers(root)
    items = data["invoices"]
    skip = set(skip_ids)
    sample = stratified_pick([i for i in items if i["id"] not in skip], sample_size, seed)
    ext = extractor or build_extractor(llm, transport, RetryPolicy(sleep=sleep))
    provider, model = llm.get("provider", ""), getattr(ext, "model", None) or llm.get("model") or ""
    replay = _Replay()
    desk = _desk(data, rules, lambda mode, _llm: replay)
    for it in sample:
        src = _duplicate_source(it, items) if it["scenario"] == "duplicate" else None
        if src:
            _add_history(desk, src)

    rows: list[dict] = []
    stopped: dict | None = None
    gap = 60.0 / max(rpm, 0.1)
    last = None

    def report(message=""):
        if progress:
            progress(dict(done=len(rows), total=len(sample), errors=sum(r["outcome"] == "error" for r in rows), message=message))

    report()
    for it in sample:
        if last is not None and clock() - last < gap:
            sleep(gap - (clock() - last))
        last = clock()
        blob = (root / it["file"]).read_bytes()
        ctype = guess_type(it["file"], None)
        if ctype == "application/xml":  # read directly, as in normal use: no AI call, no quota spent
            from .ubl import UblExtractor
            extraction = UblExtractor().extract(blob, ctype, it["file"])
            replay.next = extraction
            rid = desk.submit(it["file"], blob, ctype, "evaluation", mode="ai", llm={"provider": provider}, source="evaluation")
            rows.append(_score(it, desk.get_run(rid)))
            report()
            continue
        try:
            extraction = ext.extract(blob, ctype, it["file"])
        except NeedsVision as exc:  # a text-only model and an image: no call was wasted, it goes to review as in real use
            extraction = Extraction(empty_fields(), 0.0, {}, [f"Could not read automatically: {exc}"], provider, model)
        except DailyQuotaReached as exc:
            stopped = dict(reason="quota", message=str(exc))
            break
        except RateLimited as exc:
            stopped = dict(reason="rate_limit", message=str(exc))
            break
        except Exception as exc:  # noqa: BLE001 - every other failure is this invoice's error, never a silent fallback
            if type(exc).__name__ == "RateLimitError":  # Anthropic's SDK, after its own retries
                stopped = dict(reason="rate_limit", message=f"{type(exc).__name__}: {str(exc)[:200]}")
                break
            rows.append(dict(id=it["id"], file=it["file"], format=it["format"], lang=it["lang"], scenario=it["scenario"],
                             outcome="error", error=f"{type(exc).__name__}: {str(exc)[:240]}"))
            report()
            continue
        replay.next = extraction
        rid = desk.submit(it["file"], blob, ctype, "evaluation", mode="ai", llm={"provider": provider}, source="evaluation")
        row = _score(it, desk.get_run(rid))
        row.update(tokens_in=extraction.tokens_in, tokens_out=extraction.tokens_out)
        rows.append(row)
        report()
    report(stopped["message"] if stopped else "")
    return dict(mode="ai", provider=provider, model=model, as_of=data["as_of"], seed=seed, sample_size=sample_size,
                picked=[i["id"] for i in sample], rows=rows, attempted=len(rows), evaluated=sum(r["outcome"] == "ok" for r in rows),
                errors=sum(r["outcome"] == "error" for r in rows), stopped=stopped)


# ------------------------------------------------------------------------------------------- storage
def save_ai_rows(db: DB, provider: str, model: str, rules_version: int, rows: list[dict]) -> None:
    """Keep the latest result per sample for this provider and model. An error never replaces a scored result."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for r in rows:
        db.run("INSERT INTO eval_results(provider,model,sample_id,outcome,evaluated_at,rules_version,row) VALUES(?,?,?,?,?,?,?) "
               "ON CONFLICT(provider,model,sample_id) DO UPDATE SET outcome=excluded.outcome, evaluated_at=excluded.evaluated_at, "
               "rules_version=excluded.rules_version, row=excluded.row WHERE eval_results.outcome='error' OR excluded.outcome='ok'",
               (provider, model, r["id"], r["outcome"], now, rules_version, dumps(r)))


def evaluated_ids(db: DB, provider: str, model: str) -> list[str]:
    """Samples already scored with this model. Errors are not counted, so they are tried again."""
    return [r["sample_id"] for r in db.all("SELECT sample_id FROM eval_results WHERE provider=? AND model=? AND outcome='ok'",
                                           (provider, model))]


def ai_history(db: DB) -> list[dict]:
    """Combined totals over everything evaluated so far, one entry per provider and model, newest first."""
    out = []
    for k in db.all("SELECT provider, model, MIN(evaluated_at) first, MAX(evaluated_at) last, MIN(rules_version) rv_min, "
                    "MAX(rules_version) rv_max FROM eval_results GROUP BY provider, model ORDER BY last DESC"):
        rows = [loads(r["row"]) for r in db.all("SELECT row FROM eval_results WHERE provider=? AND model=? ORDER BY sample_id",
                                                 (k["provider"], k["model"]))]
        totals = summarize_rows(rows)
        totals.update(provider=k["provider"], model=k["model"], first_at=k["first"], last_at=k["last"],
                      rules_versions=[k["rv_min"], k["rv_max"]], samples_total=len(load_answers()["invoices"]),
                      error_rows=[r for r in rows if r["outcome"] == "error"], rows=[r for r in rows if r["outcome"] == "ok"])
        out.append(totals)
    return out


def summarize(r: dict) -> str:
    lines = [f"mode={r['mode']} invoices={r['count']} as_of={r['as_of']}",
             f"field accuracy      {r['field_accuracy']:.1%}", f"decision agreement  {r['decision_agreement']:.1%}",
             f"auto-approve rate   {r['auto_approve_rate']:.1%}", f"review rate         {r['review_rate']:.1%}",
             f"unsafe auto-approvals {r['unsafe_auto_approvals']}   false rejections {r['false_rejections']}"]
    for key in ("by_format", "by_lang"):
        for k, b in r[key].items():
            lines.append(f"  {key[3:]:7} {k:7} n={b['n']:2}  agree {b['agree']/b['n']:.0%}  fields {b['fields_ok']/b['fields_total']:.0%}")
    return "\n".join(lines)


if __name__ == "__main__":  # python -m invoice_desk.evaluation
    print(summarize(evaluate()))
