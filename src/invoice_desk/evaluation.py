"""Scores an extractor + the current rules against the answer key. Runs on a throwaway in-memory desk."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .desk import Desk
from .extractors import guess_type
from .schema import NUMERIC, SCALARS
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


def evaluate(mode: str = "rules", llm: dict | None = None, rules: list[dict] | None = None, root: Path = SAMPLES,
             extractor_factory=None, only_text: bool = False, limit: int | None = None) -> dict:
    data = load_answers(root)
    items = data["invoices"]
    if only_text:
        items = [i for i in items if i["format"] != "png"]
    if limit:
        items = items[:limit]
    desk = Desk(":memory:", today=date.fromisoformat(data["as_of"]), sync=True, extractor_factory=extractor_factory)
    desk.settings()
    if rules is not None:
        desk._save_rules(rules)
    per, ids = [], {}
    for it in items:
        blob = (root / it["file"]).read_bytes()
        ids[it["id"]] = desk.submit(it["file"], blob, guess_type(it["file"], None), "evaluation", mode=mode, llm=llm, source="evaluation")
    field_total = field_ok = 0
    by_field: dict[str, list[int]] = {k: [0, 0] for k in SCALARS}
    for it in items:
        run = desk.get_run(ids[it["id"]])
        got = run.get("extracted") or {}
        ok_fields = 0
        for k in SCALARS:
            good = _same(k, it["truth"].get(k), got.get(k), it.get("alt_names"))
            by_field[k][0] += good
            by_field[k][1] += 1
            ok_fields += good
        field_total += len(SCALARS)
        field_ok += sum(_same(k, it["truth"].get(k), got.get(k), it.get("alt_names")) for k in SCALARS)
        per.append(dict(id=it["id"], file=it["file"], format=it["format"], lang=it["lang"], scenario=it["scenario"],
                        expected=it["expected_status"], got=run["status"], agree=run["status"] == it["expected_status"],
                        fields_ok=ok_fields, fields_total=len(SCALARS), confidence=run.get("confidence"),
                        unsafe=run["status"] in AUTO and it["expected_status"] not in AUTO,
                        false_reject=run["status"] == "rejected" and it["expected_status"] != "rejected"))
    n = len(per)
    auto = [p for p in per if p["got"] in AUTO]
    stats = desk.stats()
    def slice_(key):
        out = {}
        for p in per:
            b = out.setdefault(p[key], dict(n=0, agree=0, fields_ok=0, fields_total=0))
            b["n"] += 1
            b["agree"] += p["agree"]
            b["fields_ok"] += p["fields_ok"]
            b["fields_total"] += p["fields_total"]
        return out
    return dict(mode=mode, as_of=data["as_of"], count=n,
                field_accuracy=round(field_ok / field_total, 4) if field_total else None,
                decision_agreement=round(sum(p["agree"] for p in per) / n, 4) if n else None,
                auto_approve_rate=round(len(auto) / n, 4) if n else None,
                unsafe_auto_approvals=sum(p["unsafe"] for p in per), false_rejections=sum(p["false_reject"] for p in per),
                review_rate=round(sum(p["got"] == "needs_review" for p in per) / n, 4) if n else None,
                tokens_in=stats["tokens_in"], tokens_out=stats["tokens_out"],
                by_field={k: round(a / b, 3) for k, (a, b) in by_field.items()},
                by_format=slice_("format"), by_lang=slice_("lang"), by_scenario=slice_("scenario"), rows=per)


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
