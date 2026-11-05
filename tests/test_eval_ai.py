"""AI-mode evaluation: stratified sample, pacing, 429/503 retries, and no silent fallback to the built-in reader."""
import json
import time
from collections import Counter

import httpx
import pytest
from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.db import DB
from invoice_desk.desk import Desk
from invoice_desk.evaluation import ai_history, evaluate_ai, evaluated_ids, load_answers, save_ai_rows, stratified_pick
from invoice_desk.extractors import Extraction
from invoice_desk.providers import DailyQuotaReached, GeminiExtractor, ProviderError, RateLimited, RetryPolicy
from conftest import GOOD, TODAY

ITEMS = load_answers()["invoices"]
ANSWER = {"invoice_number": "A-1", "issue_date": "2026-10-01", "seller_name": "Acme", "seller_vat": "300000000000003", "currency": "SAR",
          "subtotal": 1000, "vat_amount": 150, "total": 1150, "field_confidence": {"total": 0.9}, "line_items": [], "notes": []}
LLM = {"provider": "gemini", "key": "k", "model": "gemini-3.5-flash-lite"}


def ok_response():
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(ANSWER)}]}}]})


def scripted(*responses):
    """A fake Gemini that answers with the given responses in order, then keeps answering OK."""
    calls = []

    def handler(req):
        calls.append(req)
        return responses[len(calls) - 1]() if len(calls) <= len(responses) else ok_response()
    return httpx.MockTransport(handler), calls


def gemini(transport, sleeps):
    return GeminiExtractor("k", "gemini-3.5-flash-lite", transport, RetryPolicy(sleep=sleeps.append))


class FakeClock:
    """time.monotonic and time.sleep that move together, so pacing can be checked without waiting."""
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, s):
        self.sleeps.append(round(s, 3))
        self.now += s


# ------------------------------------------------------------------------------- retries
def test_429_honours_retry_after_then_succeeds():
    sleeps = []
    t, calls = scripted(lambda: httpx.Response(429, headers={"Retry-After": "7"}, json={"error": {"message": "slow down"}}))
    e = gemini(t, sleeps).extract(GOOD.encode(), "text/plain")
    assert e.fields["total"] == 1150.0 and sleeps == [7.0] and len(calls) == 2


def test_gemini_retry_delay_in_the_body_is_honoured():
    sleeps = []
    body = {"error": {"code": 429, "message": "Quota exceeded for GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                      "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}]}}
    t, _ = scripted(lambda: httpx.Response(429, json=body))
    gemini(t, sleeps).extract(GOOD.encode(), "text/plain")
    assert sleeps == [37.0]


def test_503_without_retry_after_backs_off_and_doubles():
    sleeps = []
    t, calls = scripted(lambda: httpx.Response(503), lambda: httpx.Response(503))
    gemini(t, sleeps).extract(GOOD.encode(), "text/plain")
    assert sleeps == [15.0, 30.0] and len(calls) == 3


def test_gives_up_after_three_retries():
    sleeps = []
    t, calls = scripted(*[lambda: httpx.Response(429, json={"error": {"message": "per minute"}})] * 10)
    with pytest.raises(RateLimited, match="after 3 retries"):
        gemini(t, sleeps).extract(GOOD.encode(), "text/plain")
    assert sleeps == [15.0, 30.0, 60.0] and len(calls) == 4


def test_daily_quota_stops_at_once():
    sleeps = []
    body = {"error": {"code": 429, "message": "Quota exceeded for metric generate_content_free_tier_requests, "
                      "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}
    t, calls = scripted(lambda: httpx.Response(429, json=body))
    with pytest.raises(DailyQuotaReached, match="daily request quota"):
        gemini(t, sleeps).extract(GOOD.encode(), "text/plain")
    assert sleeps == [] and len(calls) == 1


def test_normal_intake_does_not_retry():
    t, calls = scripted(lambda: httpx.Response(429, headers={"Retry-After": "1"}))
    with pytest.raises(ProviderError, match="429"):
        GeminiExtractor("k", "m", t).extract(GOOD.encode(), "text/plain")
    assert len(calls) == 1


# ------------------------------------------------------------------------------- stratified pick
def test_pick_is_deterministic_and_covers_everything():
    p = stratified_pick(ITEMS, 20, seed=1)
    assert len(p) == 20 and [i["id"] for i in p] == [i["id"] for i in stratified_pick(ITEMS, 20, seed=1)]
    assert [i["id"] for i in p] != [i["id"] for i in stratified_pick(ITEMS, 20, seed=2)]
    assert {i["format"] for i in p} == {"txt", "pdf", "png"}
    assert {i["lang"] for i in p} == {i["lang"] for i in ITEMS}
    assert {i["scenario"] for i in p} == {i["scenario"] for i in ITEMS}  # every defect, duplicate and the injection sample
    assert sum(i["scenario"] == "prompt_injection" for i in p) == 1


def test_pick_is_proportional():
    for n in (20, 30):
        p = stratified_pick(ITEMS, n, seed=1)
        fmt, full = Counter(i["format"] for i in p), Counter(i["format"] for i in ITEMS)
        for f in full:
            assert abs(fmt[f] - n * full[f] / len(ITEMS)) <= 1.5, (n, f, fmt)
        clean = sum(i["scenario"] == "clean" for i in p)
        assert abs(clean - n * 31 / 60) <= 2, (n, clean)


def test_pick_skips_what_is_already_done():
    first = {i["id"] for i in stratified_pick(ITEMS, 20, seed=1)}
    rest = [i for i in ITEMS if i["id"] not in first]
    second = stratified_pick(rest, 20, seed=1)
    assert len(second) == 20 and not first & {i["id"] for i in second}
    assert len(stratified_pick(ITEMS, 100)) == 60 and stratified_pick(ITEMS, 0) == []


# ------------------------------------------------------------------------------- the run
def test_failed_calls_are_errors_never_a_silent_fallback():
    """Every third call fails. Those invoices must be errors, not read by the built-in reader."""
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        return httpx.Response(500, json={"error": {"message": "boom"}}) if n["calls"] % 3 == 0 else ok_response()
    fc = FakeClock()
    r = evaluate_ai(LLM, sample_size=9, rpm=60, transport=httpx.MockTransport(handler), sleep=fc.sleep, clock=fc.clock)
    errors = [x for x in r["rows"] if x["outcome"] == "error"]
    assert (r["attempted"], r["evaluated"], r["errors"]) == (9, 6, 3) and len(errors) == 3
    assert all("500" in x["error"] and "fields_ok" not in x for x in errors)
    # the scored ones carry Gemini's answer, not what the rule-based reader would have found
    assert all(x["fields_ok"] < x["fields_total"] for x in r["rows"] if x["outcome"] == "ok")


def test_all_calls_failing_gives_no_accuracy_at_all():
    fc = FakeClock()
    t = httpx.MockTransport(lambda req: httpx.Response(500))
    r = evaluate_ai(LLM, sample_size=4, rpm=60, transport=t, sleep=fc.sleep, clock=fc.clock)
    assert (r["evaluated"], r["errors"]) == (0, 4)
    from invoice_desk.evaluation import summarize_rows
    s = summarize_rows(r["rows"])
    assert s["count"] == 0 and s["errors"] == 4 and s["decision_agreement"] is None and s["field_accuracy"] is None


def test_daily_quota_stops_the_run_and_keeps_what_was_done():
    calls = {"n": 0}
    quota = {"error": {"code": 429, "message": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}}

    def handler(req):
        calls["n"] += 1
        return ok_response() if calls["n"] <= 3 else httpx.Response(429, json=quota)
    fc = FakeClock()
    r = evaluate_ai(LLM, sample_size=20, rpm=60, transport=httpx.MockTransport(handler), sleep=fc.sleep, clock=fc.clock)
    assert r["stopped"]["reason"] == "quota" and "daily request quota" in r["stopped"]["message"]
    assert (r["attempted"], r["evaluated"], r["errors"]) == (3, 3, 0) and len(r["picked"]) == 20 and calls["n"] == 4


def test_pacing_spaces_the_calls():
    fc = FakeClock()
    times = []

    def handler(req):
        times.append(fc.now)
        return ok_response()
    evaluate_ai(LLM, sample_size=4, rpm=4, transport=httpx.MockTransport(handler), sleep=fc.sleep, clock=fc.clock)
    assert [round(b - a) for a, b in zip(times, times[1:])] == [15, 15, 15]


def test_a_perfect_model_on_a_sample_scores_perfectly():
    """Duplicates in a small sample still need their original: it is added as history, so a perfect reader gets every decision right."""
    truth = {i["file"]: i["truth"] for i in ITEMS}

    class Oracle:
        model = "oracle"

        def extract(self, blob, ct, name):
            return Extraction(dict(truth[name]), 1.0, {}, [], "oracle", "oracle")
    fc = FakeClock()
    r = evaluate_ai(LLM, sample_size=20, rpm=60, extractor=Oracle(), sleep=fc.sleep, clock=fc.clock)
    assert any(i["scenario"] == "duplicate" for i in ITEMS if i["id"] in r["picked"])
    assert r["evaluated"] == 20 and all(x["agree"] for x in r["rows"]), [x for x in r["rows"] if not x["agree"]]


# ------------------------------------------------------------------------------- storage and totals
def row(sid, outcome="ok", agree=True):
    it = next(i for i in ITEMS if i["id"] == sid)
    base = dict(id=sid, file=it["file"], format=it["format"], lang=it["lang"], scenario=it["scenario"], outcome=outcome)
    if outcome == "error":
        return dict(base, error="boom")
    return dict(base, expected="approved", got="approved" if agree else "needs_review", agree=agree, fields_ok=10,
                fields_total=12, field_hits={}, unsafe=False, false_reject=False)


def test_results_accumulate_per_model_and_errors_do_not_replace_scores():
    db = DB()
    save_ai_rows(db, "gemini", "m1", 1, [row("inv-001"), row("inv-002", "error"), row("inv-003", agree=False)])
    save_ai_rows(db, "gemini", "m1", 1, [row("inv-001", "error"), row("inv-002"), row("inv-004")])  # day two
    save_ai_rows(db, "gemini", "m2", 1, [row("inv-001")])
    assert sorted(evaluated_ids(db, "gemini", "m1")) == ["inv-001", "inv-002", "inv-003", "inv-004"]
    h = {x["model"]: x for x in ai_history(db)}
    assert h["m1"]["count"] == 4 and h["m1"]["errors"] == 0 and h["m1"]["decision_agreement"] == 0.75
    assert h["m2"]["count"] == 1 and h["m1"]["first_at"] and h["m1"]["last_at"]
    save_ai_rows(db, "gemini", "m1", 2, [row("inv-005", "error")])
    h = {x["model"]: x for x in ai_history(db)}
    assert h["m1"]["count"] == 4 and h["m1"]["errors"] == 1 and "inv-005" not in evaluated_ids(db, "gemini", "m1")


def test_api_runs_an_ai_evaluation_and_reports_totals(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=1000,
                              eval_transport=httpx.MockTransport(lambda req: ok_response())))
    a = {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "admin"}).json()["token"]}
    ai = {**a, "X-LLM-Provider": "gemini", "X-LLM-Key": "k", "X-LLM-Model": "gemini-3.5-flash-lite"}
    assert c.post("/api/evaluation/run", json={"mode": "ai", "sample_size": 0}, headers=ai).status_code == 400
    assert c.post("/api/evaluation/run", json={"mode": "ai"}, headers=a).status_code == 400  # no provider chosen
    job = c.post("/api/evaluation/run", json={"mode": "ai", "sample_size": 2, "rpm": 60}, headers=ai).json()["job"]
    for _ in range(100):
        j = c.get(f"/api/evaluation/jobs/{job}", headers=a).json()
        if j["status"] != "running":
            break
        time.sleep(0.1)
    assert j["status"] == "done" and (j["evaluated"], j["errors"], j["total"]) == (2, 0, 2), j
    out = c.get("/api/evaluation", headers=a).json()
    assert out["ai_last"]["evaluated"] == 2 and out["ai_last"]["model"] == "gemini-3.5-flash-lite"
    assert out["ai_models"][0]["count"] == 2 and out["ai_models"][0]["model"] == "gemini-3.5-flash-lite"
    job = c.post("/api/evaluation/run", json={"mode": "ai", "sample_size": 2, "rpm": 60, "only_new": True}, headers=ai).json()["job"]
    for _ in range(100):
        j = c.get(f"/api/evaluation/jobs/{job}", headers=a).json()
        if j["status"] != "running":
            break
        time.sleep(0.1)
    assert c.get("/api/evaluation", headers=a).json()["ai_models"][0]["count"] == 4
