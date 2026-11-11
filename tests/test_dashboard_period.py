"""Demo history (sample invoices dated over 30 days), period figures for the dashboard, and the activity feed."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.desk import Desk, DeskError
from invoice_desk.samples import DEMO_REVIEWERS, DEMO_SET, demo_plan, history_set, load_answers, sample_bytes
from conftest import GOOD, TODAY

END = datetime(2026, 11, 5, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 5, 15, 0, tzinfo=timezone.utc)
ANSWERS = {i["file"]: i for i in load_answers()["invoices"]}


class SteppingClock:
    """A clock that never reads the real time: it starts at a fixed moment and moves on one second at every read, so
    two reads are always different seconds. Code that takes two readings for one event shows up here every time,
    not once in a few hundred runs when the real clock happens to cross a second."""
    def __init__(self, start: datetime):
        self.moment = start

    def __call__(self) -> datetime:
        self.moment += timedelta(seconds=1)
        return self.moment


CLOCK_START = datetime(2026, 11, 6, 12, 0, tzinfo=timezone.utc)          # after the plan's NOW, like the real clock is


@pytest.fixture(scope="module")
def demo():
    d = Desk(":memory:", today=TODAY, sync=True, seed_vendors=True, clock=SteppingClock(CLOCK_START))
    plan = demo_plan(END, NOW)
    ids = d.load_demo("demo-admin", plan, sample_bytes)
    return d, plan, ids


def test_history_set_cannot_turn_a_welcome_invoice_into_a_duplicate():
    hist = history_set()
    files = {i["file"] for i in hist}
    assert len(hist) > 40 and not files & set(DEMO_SET)
    assert not any(i["vision_only"] or i["scenario"] == "duplicate" for i in hist)
    copied = {ANSWERS[f].get("copy_of") for f in DEMO_SET} - {None}
    assert copied and not copied & {i["id"] for i in hist}


def test_plan_is_in_date_order_inside_30_days_and_never_in_the_future():
    plan = demo_plan(END, NOW)
    ats = [p["at"] for p in plan]
    assert ats == sorted(ats) and max(ats) <= NOW
    first_day = (END - timedelta(days=29)).date()
    assert min(ats).date() >= first_day
    welcome = [p for p in plan if p["file"] in DEMO_SET]
    assert len(welcome) == 20 and all(p["decide"] is None for p in welcome)
    assert all((END.date() - p["at"].date()).days <= 6 for p in welcome)
    waiting = [p for p in welcome if ANSWERS[p["file"]]["expected_status"] == "needs_review"]
    assert all((END.date() - p["at"].date()).days <= 1 for p in waiting)
    history = [p for p in plan if p["file"] not in DEMO_SET]
    assert all(2 <= (END.date() - p["at"].date()).days <= 29 for p in history)
    assert {p["decide"]["actor"] for p in history} == set(DEMO_REVIEWERS)
    assert demo_plan(END, NOW) == plan                                   # the same every time
    assert len(demo_plan(END, NOW, history=False)) == 20


def test_plan_stays_before_now_early_in_the_day():
    early = END + timedelta(hours=1)                                     # 04:00 in Riyadh, before working hours
    assert max(p["at"] for p in demo_plan(END, early)) <= early


def test_demo_load_keeps_the_welcome_mix_and_decides_the_history(demo):
    d, plan, ids = demo
    runs = {i: d.get_run(i) for i in ids}
    welcome = Counter(runs[i]["status"] for i, p in zip(ids, plan) if p["file"] in DEMO_SET)
    assert welcome == {"approved": 11, "needs_review": 6, "rejected": 3}
    history = [runs[i] for i, p in zip(ids, plan) if p["file"] not in DEMO_SET]
    assert not any(r["status"] in ("needs_review", "queued", "processing") for r in history)
    people = [r for r in history if r["status"] in ("approved_human", "rejected_human")]
    assert people and {r["decision_by"] for r in people} <= set(DEMO_REVIEWERS)
    assert all(r["decision_note"] for r in people if r["status"] == "rejected_human")
    for r in people:                                                     # a person never approves an unreadable invoice
        if r["status"] == "approved_human":
            assert r["fields"]["seller_name"] and r["fields"]["total"] is not None
    assert len(d.review_queue()) == 6


def test_demo_runs_carry_their_planned_dates(demo):
    d, plan, ids = demo
    created = []
    for rid, p in zip(ids, plan):
        r = d.get_run(rid)
        assert r["created_at"] == p["at"].isoformat(timespec="seconds")
        assert r["trace"][0]["at"] == r["created_at"]
        if r["status"] in ("approved_human", "rejected_human"):
            assert r["created_at"] < r["decided_at"] and r["trace"][-1]["at"] == r["decided_at"]
        elif r["decided_at"]:
            assert r["decided_at"][:10] == r["created_at"][:10]
        created.append(r["created_at"])
    assert created == sorted(created)                                    # ids follow dates
    reviews = [a for a in d.audit_log(1000) if a["action"].startswith("review.")]
    assert reviews and all(a["ts"] == d.get_run(int(a["target"]))["decided_at"] for a in reviews)
    submits = [a for a in d.audit_log(1000) if a["action"] == "run.submit"]
    assert all(a["ts"] == d.get_run(int(a["target"]))["created_at"] for a in submits)


def test_one_event_is_one_moment_whatever_the_clock_does():
    """created_at and the run.submit audit row, the outcome and its audit row, a decision and its trace step and audit row:
    each pair is a single reading of the clock. With a clock that moves a second at every read, two readings would differ."""
    d = Desk(":memory:", today=TODAY, sync=True, clock=SteppingClock(CLOCK_START))
    d.update_settings({"auto_approve": "false"}, "a")                      # so a clean invoice waits for a person
    rid = d.submit("a.txt", GOOD.encode(), "text/plain", "r")
    run = d.get_run(rid)
    assert run["status"] == "needs_review"
    at = {a["action"]: a["ts"] for a in d.audit_log(100) if a["target"] == str(rid)}
    assert run["created_at"] == at["run.submit"] and run["decided_at"] is None
    assert run["updated_at"] == at["run.decision"]
    done = d.review(rid, "approve", "noura", note="ok")
    assert done["decided_at"] == done["updated_at"] == done["trace"][-1]["at"]
    assert done["decided_at"] == next(a["ts"] for a in d.audit_log(100) if a["action"] == "review.approve")
    d.update_settings({"auto_approve": "true"}, "a")
    auto = d.submit("b.txt", GOOD.replace("ACM-2026-0001", "ACM-2026-0002").encode(), "text/plain", "r")
    row = d.get_run(auto)
    assert row["status"] == "approved" and row["decided_at"] == row["updated_at"]
    assert row["decided_at"] == next(a["ts"] for a in d.audit_log(100) if a["target"] == str(auto) and a["action"] == "run.decision")


def test_period_figures_and_previous_window(demo):
    d, plan, ids = demo
    p30 = d.stats("upload", 30)["period"]
    assert (p30["days"], p30["start"], p30["end"]) == (30, "2026-10-07", "2026-11-05")
    assert p30["current"]["received"] == len(ids) and p30["previous"]["received"] == 0
    assert len(p30["series"]) == 30 and p30["series"][-1]["day"] == "2026-11-05"
    by = Counter()
    for x in p30["series"]:
        by.update({k: x[k] for k in ("auto", "person", "review", "rejected")})
    c = p30["current"]
    assert by["auto"] == c["approved"] and by["person"] == c["approved_human"] and by["review"] == c["waiting"] == 6
    assert by["rejected"] == c["rejected"] and sum(by.values()) == c["received"]
    assert c["avg_time_to_review_s"] and c["avg_time_to_review_s"] > 0
    p7 = d.stats("upload", 7)["period"]
    week = sum(1 for p in plan if (END.date() - p["at"].date()).days < 7)
    assert week > 20 and p7["current"]["received"] == week and p7["previous"]["received"] > 0
    assert p7["current"]["approved_human"] + p7["current"]["rejected"] > 0       # the last week has decisions too
    assert p7["current"]["avg_time_to_review_s"] is not None
    assert p7["waiting_count"] == 6 and len(p7["waiting"]) == 5
    assert [w["id"] for w in p7["waiting"]] == sorted(w["id"] for w in p7["waiting"])
    assert p7["waiting"][0]["created_at"] <= p7["waiting"][-1]["created_at"]
    assert p7["waiting_value"] == round(sum(w["total"] for w in d.review_queue() if w["currency"] == "SAR"), 2)
    assert p7["high_risk"] == sum(1 for w in d.review_queue() if w["high_risk"])


def test_money_is_summed_in_sar_and_other_currencies_are_counted(desk):
    desk.submit("a.txt", GOOD.encode(), "text/plain", "r")
    usd = GOOD.replace("ACM-2026-0001", "ACM-2026-0002").replace("Currency: SAR", "Currency: USD").replace(" SAR", " USD")
    desk.submit("b.txt", usd.encode(), "text/plain", "r")
    p = desk.stats("upload", 7)["period"]
    assert p["current"]["value"]["approved"] == 1150.0
    assert p["current"]["other_currency"] == 1


def test_due_soon_counts_approved_invoices_due_within_a_week(desk):
    soon = GOOD.replace("Due Date: 2026-11-01", "Due Date: 2026-11-09")
    late = GOOD.replace("ACM-2026-0001", "ACM-2026-0003").replace("Due Date: 2026-11-01", "Due Date: 2026-12-20")
    desk.submit("a.txt", soon.encode(), "text/plain", "r")
    desk.submit("b.txt", late.encode(), "text/plain", "r")
    due = desk.stats("upload", 30)["period"]["due_soon"]
    assert due == {"count": 1, "value": 1150.0, "other_currency": 0}


def test_today_is_drawn_by_the_hour_against_yesterday(desk):
    today = desk.submit("a.txt", GOOD.encode(), "text/plain", "r")
    desk._backdate(today, datetime(2026, 11, 5, 9, 30, tzinfo=timezone.utc))
    yesterday = desk.submit("b.txt", GOOD.replace("ACM-2026-0001", "ACM-2026-0002").encode(), "text/plain", "r")
    desk._backdate(yesterday, datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc))
    p = desk.stats("upload", 1)["period"]
    assert (p["days"], p["start"], p["end"]) == (1, "2026-11-05", "2026-11-05")
    assert p["current"]["received"] == 1 and p["previous"]["received"] == 1
    assert len(p["series"]) == 24 and p["series"][0]["day"] == "2026-11-05T00:00:00+00:00"
    hour = {x["day"]: x for x in p["series"]}["2026-11-05T09:00:00+00:00"]
    assert hour["auto"] == 1 and hour["value"] == 1150.0
    assert sum(x["auto"] for x in p["series"]) == 1


def test_period_has_no_insight_block(desk):
    desk.submit("a.txt", GOOD.encode(), "text/plain", "r")
    assert "insight" not in desk.stats("upload", 7)["period"]


def test_period_must_be_today_7_30_or_90(desk, auth):
    with pytest.raises(DeskError):
        desk.stats("upload", 14)
    assert "period" not in desk.stats("upload")
    c = TestClient(create_app(desk, auth))
    v = {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "viewer"}).json()["token"]}
    assert c.get("/api/stats?days=14", headers=v).status_code == 400
    assert c.get("/api/stats?days=90", headers=v).json()["period"]["days"] == 90
    assert c.get("/api/stats?days=1", headers=v).json()["period"]["days"] == 1


def test_activity_shows_what_people_did_newest_first(demo, auth):
    d, _, _ = demo
    rows = d.activity(50)
    assert rows and all(a["action"] in Desk.ACTIVITY for a in rows)
    assert [a["ts"] for a in rows] == sorted((a["ts"] for a in rows), reverse=True)
    reviews = [a for a in rows if a["action"].startswith("review.")]
    assert reviews and all(a["run"] and "seller_name" in a["run"] and a["run"]["filename"] for a in reviews)
    assert len(d.activity(3)) == 3
    c = TestClient(create_app(d, auth))
    v = {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "viewer"}).json()["token"]}
    assert len(c.get("/api/activity?limit=4", headers=v).json()) == 4
    assert c.get("/api/activity").status_code == 401


def test_api_demo_load_with_history(auth):
    d = Desk(":memory:", today=TODAY, sync=True, seed_vendors=True)
    c = TestClient(create_app(d, auth, rate_limit=1000))
    r = {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "reviewer"}).json()["token"]}
    body = c.post("/api/samples/demo", headers=r).json()
    assert len(body["welcome"]) == 20 and len(body["ids"]) == 20 + len(history_set())
    assert set(body["welcome"]) <= set(body["ids"])
    assert d.stats("upload")["review_queue"] == 6
    assert d.activity(1)[0]["action"] == "demo.samples"
    assert date.fromisoformat(d.list_runs(limit=1)["items"][0]["created_at"][:10]) <= TODAY
