"""Run sources, duplicates per source, dashboard filter and rejection reasons, the welcome sample set, demo reset."""
from collections import Counter

from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.desk import Desk
from invoice_desk.evaluation import evaluate
from invoice_desk.samples import DEMO_SET, load_answers
from conftest import GOOD, TODAY

ANSWERS = {i["file"]: i for i in load_answers()["invoices"]}


def test_duplicates_only_count_within_the_same_source(desk):
    first = desk.submit("a.txt", GOOD.encode(), "text/plain", "r", source="evaluation")
    assert desk.get_run(first)["status"] == "approved"
    up = desk.submit("a.txt", GOOD.encode(), "text/plain", "r")
    assert desk.get_run(up)["status"] == "approved"            # an evaluation run does not make an upload a duplicate
    again = desk.submit("a.txt", GOOD.encode(), "text/plain", "r")
    assert desk.get_run(again)["status"] == "rejected"         # a second upload still is one
    ev = desk.submit("a.txt", GOOD.encode(), "text/plain", "r", source="evaluation")
    assert desk.get_run(ev)["status"] == "rejected"


def test_old_sample_rows_become_uploads(tmp_path):
    path = str(tmp_path / "d.db")
    d = Desk(path, today=TODAY, sync=True)
    rid = d.submit("a.txt", GOOD.encode(), "text/plain", "r")
    d.db.run("UPDATE runs SET source='sample' WHERE id=?", (rid,))
    assert Desk(path, today=TODAY, sync=True).get_run(rid)["source"] == "upload"


def test_stats_filter_by_source_and_rejection_reasons(desk):
    desk.submit("a.txt", GOOD.encode(), "text/plain", "r")
    desk.submit("a.txt", GOOD.encode(), "text/plain", "r")                     # duplicate: rejected
    desk.submit("b.txt", GOOD.replace("300000000000003", "123").encode(), "text/plain", "r")
    desk.submit("e.txt", GOOD.encode(), "text/plain", "r", source="evaluation")
    up, ev, every = desk.stats("upload"), desk.stats("evaluation"), desk.stats()
    assert (up["total"], ev["total"], every["total"]) == (3, 1, 4)
    assert up["source"] == "upload" and every["source"] == "all" and up["uploads"] == 3
    reasons = {x["reason"]: x["count"] for x in up["top_rejections"]}
    assert reasons["Not a duplicate"] == 1 and sum(reasons.values()) >= 2
    assert ev["top_rejections"] == []


def test_human_rejection_is_a_reason_and_evaluation_runs_stay_out_of_the_queue(desk):
    rid = desk.submit("x.txt", GOOD.replace("Total (including VAT): 1,150.00", "Total (including VAT): 70,000.00").encode(), "text/plain", "r")
    assert desk.get_run(rid)["status"] in ("needs_review", "rejected")
    review = desk.submit("y.txt", GOOD.replace("Due Date: 2026-11-01\n", "").replace("Buyer: Beta Foods", "").encode(), "text/plain", "r")
    queue = [q["id"] for q in desk.review_queue()]
    if review in queue:
        desk.review(review, "reject", "r", note="not ours")
        assert any(x["reason"] == "Rejected by a reviewer" for x in desk.stats("upload")["top_rejections"])
    ev = desk.submit("z.txt", GOOD.replace("ACM-2026-0001", "ACM-2026-0099").replace("Currency: SAR", "Currency: USD").encode(),
                     "text/plain", "r", source="evaluation")
    assert desk.get_run(ev)["status"] == "needs_review"
    assert ev not in [q["id"] for q in desk.review_queue()] and desk.stats()["review_queue"] == len(desk.review_queue())
    try:
        desk.review(ev, "approve", "r")
        raise AssertionError("evaluation runs must not be reviewed")
    except Exception as exc:  # noqa: BLE001
        assert "not reviewed" in str(exc)


def test_welcome_set_mix():
    assert len(DEMO_SET) == 20 and len(set(DEMO_SET)) == 20
    items = [ANSWERS[f] for f in DEMO_SET]
    mix = Counter(i["expected_status"] for i in items)
    assert mix == {"approved": 11, "needs_review": 6, "rejected": 3}
    assert {i["format"] for i in items} == {"txt", "pdf", "xml"} and {i["lang"] for i in items} >= {"en", "ar"}
    assert not any(i["vision_only"] or i["scenario"] == "duplicate" for i in items)


def test_evaluation_runs_are_recorded_tagged_and_kept_off_the_dashboard(auth):
    d = Desk(":memory:", today=TODAY, sync=True, seed_vendors=True)
    res = evaluate(limit=5)
    runs = res.pop("_runs")
    assert len(runs) == 5 and all(r["source"] == "evaluation" for r in runs)
    d.record_evaluation_runs(runs)
    assert d.stats("upload")["total"] == 0 and d.stats("evaluation")["total"] == 5
    assert d.list_runs(source="evaluation")["total"] == 5 and d.list_runs(source="upload")["total"] == 0


def test_api_welcome_set_stats_and_reset(auth):
    d = Desk(":memory:", today=TODAY, sync=True, seed_vendors=True)
    c = TestClient(create_app(d, auth, rate_limit=1000))
    tok = lambda role: {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": role}).json()["token"]}  # noqa: E731
    v, r, a = tok("viewer"), tok("reviewer"), tok("admin")
    assert c.post("/api/samples/demo", headers=v).status_code == 403
    ids = c.post("/api/samples/demo", headers=r).json()["ids"]
    assert len(ids) == 20
    got = Counter(c.get(f"/api/runs/{i}", headers=v).json()["status"] for i in ids)
    assert got == {"approved": 11, "needs_review": 6, "rejected": 3}            # the reader agrees with the answer key
    s = c.get("/api/stats", headers=v).json()
    assert s["source"] == "upload" and s["total"] == 20 and s["review_queue"] == 6 and s["top_rejections"]
    assert c.get("/api/stats?source=all", headers=v).json()["source"] == "all"
    assert c.get("/api/stats?source=nope", headers=v).status_code == 400
    assert c.get("/api/runs?source=upload", headers=v).json()["total"] == 20
    assert c.post("/api/admin/reset", json={}, headers=r).status_code == 403
    n_vendors = len(c.get("/api/vendors", headers=v).json())
    assert c.post("/api/admin/reset", json={}, headers=a).status_code == 200
    assert c.get("/api/stats", headers=v).json()["total"] == 0
    assert len(c.get("/api/vendors", headers=v).json()) == n_vendors
    assert [x["action"] for x in c.get("/api/audit", headers=a).json()] == ["demo.reset"]
