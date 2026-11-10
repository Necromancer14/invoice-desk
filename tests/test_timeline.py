"""The per-invoice timeline in run detail: received, read, checked, routed, reviewed, read again."""
from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.desk import Desk

from conftest import GOOD, TODAY

NO_NUMBER = GOOD.replace("Invoice No: ACM-2026-0001\n", "")


def kinds(run):
    return [e["kind"] for e in run["timeline"]]


def test_auto_approved_invoice(desk):
    rid = desk.submit("a.txt", GOOD.encode(), "text/plain", "maaz")
    tl = desk.get_run(rid)["timeline"]
    assert [e["kind"] for e in tl] == ["received", "read", "checked", "routed"]
    received, read, checked, routed = tl
    assert received["actor"] == "maaz" and received["mode"] == "rules"
    assert read["reader"] == "rule-based" and read["ok"] and not read["fell_back"]
    assert checked["rules_version"] == desk.rules_version()
    # the counts are those at intake, as the trace recorded them
    results = desk.get_run(rid)["results"]
    assert checked["checks"] == len(results)
    assert checked["failed"] == sum(1 for x in results if x["status"] == "fail")
    assert routed["outcome"] == "approved" and not routed["auto_approve_off"]
    assert [e["at"] for e in tl] == sorted(e["at"] for e in tl)


def test_review_with_edits_and_note(desk):
    rid = desk.submit("a.txt", NO_NUMBER.encode(), "text/plain", "t")
    run = desk.get_run(rid)
    assert kinds(run)[-1] == "routed" and run["timeline"][-1]["outcome"] == "needs_review"
    assert run["timeline"][2]["failed"] >= 1
    run = desk.review(rid, "approve", "noura", {"invoice_number": "ACM-77", "total": "1150"}, "typed from the paper copy")
    last = run["timeline"][-1]
    assert last == dict(kind="reviewed", at=last["at"], actor="noura", decision="approve",
                        note="typed from the paper copy", edited=["invoice_number"])


def test_reject_without_edits(desk):
    rid = desk.submit("a.txt", NO_NUMBER.encode(), "text/plain", "t")
    last = desk.review(rid, "reject", "faisal", note="not ours")["timeline"][-1]
    assert (last["decision"], last["note"], last["edited"]) == ("reject", "not ours", [])


def test_auto_approve_off_is_said(desk):
    desk.update_settings({"auto_approve": "false"}, "admin")
    rid = desk.submit("a.txt", GOOD.encode(), "text/plain", "t")
    routed = desk.get_run(rid)["timeline"][-1]
    assert routed["outcome"] == "needs_review" and routed["auto_approve_off"]


def test_read_again_keeps_the_earlier_outcome(desk):
    rid = desk.submit("a.txt", NO_NUMBER.encode(), "text/plain", "t")
    desk.review(rid, "reject", "faisal", note="not ours")
    desk.reprocess(rid, "admin")
    k = kinds(desk.get_run(rid))
    # the first processing shows its outcome only; the latest one has its reader and checks
    assert k == ["received", "routed", "reviewed", "reprocess", "read", "checked", "routed"]


def test_failed_processing(desk):
    desk.extractor_factory = lambda mode, llm: (_ for _ in ()).throw(RuntimeError("boom"))
    rid = desk.submit("a.txt", GOOD.encode(), "text/plain", "t")
    assert kinds(desk.get_run(rid))[-1] == "failed"


def test_other_runs_do_not_leak_in(desk):
    a = desk.submit("a.txt", NO_NUMBER.encode(), "text/plain", "t")
    b = desk.submit("b.txt", NO_NUMBER.encode(), "text/plain", "t")
    desk.review(b, "reject", "faisal", note="not ours")
    assert "reviewed" not in kinds(desk.get_run(a))


def test_api_returns_the_timeline():
    d = Desk(":memory:", today=TODAY, sync=True)
    client = TestClient(create_app(desk=d))
    tok = client.post("/api/auth/demo", json={"role": "viewer"}).json()["token"]
    rid = d.submit("a.txt", GOOD.encode(), "text/plain", "t")
    run = client.get(f"/api/runs/{rid}", headers={"Authorization": f"Bearer {tok}"}).json()
    assert [e["kind"] for e in run["timeline"]] == ["received", "read", "checked", "routed"]
