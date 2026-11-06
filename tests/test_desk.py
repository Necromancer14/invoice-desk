import pytest

from invoice_desk.default_rules import DEFAULT_RULES
from invoice_desk.desk import Desk, DeskError
from invoice_desk.extractors import Extraction
from invoice_desk.schema import empty_fields
from conftest import GOOD, TODAY


def test_clean_invoice_is_auto_approved(desk, good):
    rid = desk.submit("a.txt", good, "text/plain", "tester")
    run = desk.get_run(rid)
    assert run["status"] == "approved" and run["fields"]["total"] == 1150.0
    assert [t["step"] for t in run["trace"]][:4] == ["ingest", "extract", "validate", "route"]


def test_wrong_vat_is_rejected(desk):
    rid = desk.submit("a.txt", GOOD.replace("150.00 SAR", "100.00 SAR").encode(), "text/plain", "t")
    assert desk.get_run(rid)["status"] == "rejected"


def test_missing_field_goes_to_review_and_human_can_fix_and_approve(desk):
    rid = desk.submit("a.txt", GOOD.replace("Invoice No: ACM-2026-0001\n", "").encode(), "text/plain", "t")
    assert desk.get_run(rid)["status"] == "needs_review"
    out = desk.review(rid, "approve", "rev", {"invoice_number": "ACM-77"}, "typed from the paper copy")
    assert out["status"] == "approved_human" and out["fields"]["invoice_number"] == "ACM-77" and out["edited"]
    assert out["extracted"]["invoice_number"] is None  # the original extraction is kept for the audit trail
    assert any(a["action"] == "review.approve" for a in desk.audit_log())


def test_review_rules(desk):
    rid = desk.submit("a.txt", GOOD.replace("Invoice No: ACM-2026-0001\n", "").encode(), "text/plain", "t")
    with pytest.raises(DeskError, match="note"):
        desk.review(rid, "reject", "rev")
    with pytest.raises(DeskError, match="decision"):
        desk.review(rid, "maybe", "rev")
    with pytest.raises(DeskError, match="number"):
        desk.review(rid, "approve", "rev", {"total": "lots"})
    desk.review(rid, "reject", "rev", note="not ours")
    with pytest.raises(DeskError) as e:
        desk.review(rid, "approve", "rev")
    assert e.value.status == 409


def test_duplicate_detection(desk, good):
    first = desk.submit("a.txt", good, "text/plain", "t")
    second = desk.submit("b.txt", good, "text/plain", "t")
    assert desk.get_run(first)["status"] == "approved" and desk.get_run(second)["status"] == "rejected"


def test_upload_validation(desk):
    for args, status in [(("a.exe", b"x", "application/x-msdownload"), 415), (("a.txt", b"", "text/plain"), 400),
                         (("a.txt", b"x" * (5 * 1024 * 1024 + 1), "text/plain"), 413)]:
        with pytest.raises(DeskError) as e:
            desk.submit(*args, "t")
        assert e.value.status == status
    with pytest.raises(DeskError, match="provider"):
        desk.submit("a.txt", b"x", "text/plain", "t", mode="ai")
    with pytest.raises(DeskError, match="needs an API key"):
        desk.submit("a.txt", b"x", "text/plain", "t", mode="ai", llm={"provider": "gemini", "key": ""})


def test_image_without_an_ai_model_lands_in_review(desk):
    rid = desk.submit("scan.png", b"\x89PNG", "image/png", "t")
    run = desk.get_run(rid)
    assert run["status"] == "needs_review" and "Could not read" in run["extraction"]["notes"][0]


def test_extractor_crash_marks_run_failed(good):
    class Boom:
        def extract(self, *a):
            raise RuntimeError("kaput")
    d = Desk(":memory:", today=TODAY, sync=True, extractor_factory=lambda *a: Boom())
    run = d.get_run(d.submit("a.txt", good, "text/plain", "t"))
    assert run["status"] == "failed" and "kaput" in run["error"]


def test_ai_failure_falls_back_to_rules(good):
    class Boom:
        def extract(self, *a):
            raise RuntimeError("api down")
    d = Desk(":memory:", today=TODAY, sync=True, extractor_factory=lambda mode, *a: Boom() if mode == "ai" else __import__("invoice_desk.extractors", fromlist=["x"]).RuleBasedExtractor())
    run = d.get_run(d.submit("a.txt", good, "text/plain", "t", mode="ai", llm={"provider": "x"}))
    assert run["status"] == "approved" and any("fall" in t["detail"] for t in run["trace"])


def test_api_key_is_never_stored(good):
    seen = {}
    class Spy:
        def extract(self, blob, ct, name):
            return Extraction(empty_fields(), 0.1)
    d = Desk(":memory:", today=TODAY, sync=True, extractor_factory=lambda mode, llm: seen.update(key=llm["key"]) or Spy())
    d.submit("a.txt", good, "text/plain", "t", mode="ai", llm={"provider": "claude", "key": "sk-ant-secret"})
    assert seen["key"] == "sk-ant-secret"
    dump = " ".join(str(r) for t in ("runs", "audit", "settings", "rule_versions") for r in d.db.all(f"SELECT * FROM {t}"))
    assert "sk-ant-secret" not in dump


# ---- rules admin --------------------------------------------------------------------------
def test_rule_crud_versions_and_rollback(desk, good):
    v0 = desk.rules_version()
    n = len(desk.rules())
    out = desk.upsert_rule(dict(name="Block big invoices", type="amount_limit", severity="reject", params={"field": "total", "max": 1000}), "admin")
    assert out["rule"]["key"] == "block-big-invoices" and len(desk.rules()) == n + 1 and desk.rules_version() == v0 + 1
    rid = desk.submit("a.txt", good, "text/plain", "t")
    assert desk.get_run(rid)["status"] == "rejected"  # new rule applies immediately, no deploy
    desk.rollback(v0, "admin")
    assert len(desk.rules()) == n
    rid2 = desk.submit("b.txt", good.replace(b"0001", b"0002"), "text/plain", "t")
    assert desk.get_run(rid2)["status"] == "approved"
    assert any(v["note"].startswith("Rolled back") for v in desk.rule_versions())


def test_rule_validation_errors_are_readable(desk):
    with pytest.raises(DeskError, match="not allowed|helper|unknown"):
        desk.upsert_rule(dict(name="x", type="expression", severity="review", params={"expr": "__import__('os')"}), "a")
    with pytest.raises(DeskError, match="key"):
        desk.upsert_rule(dict(key="Bad Key!", name="x", type="duplicate", severity="review"), "a")


def test_disable_and_delete_and_reorder(desk):
    r = desk.rules()[3]
    desk.upsert_rule(dict(r, enabled=False), "a")
    assert not next(x for x in desk.rules() if x["key"] == r["key"])["enabled"]
    desk.delete_rule(r["key"], "a")
    assert r["key"] not in [x["key"] for x in desk.rules()]
    keys = [x["key"] for x in desk.rules()][::-1]
    desk.reorder_rules(keys, "a")
    assert [x["key"] for x in desk.rules()] == keys
    with pytest.raises(DeskError):
        desk.reorder_rules(keys[:-1], "a")
    with pytest.raises(DeskError):
        desk.delete_rule("nope", "a")


def test_simulate_shows_impact_without_changing_anything(desk, good):
    desk.submit("a.txt", good, "text/plain", "t")
    before = desk.rules_version()
    sim = desk.simulate(rule=dict(name="Tiny limit", type="amount_limit", severity="reject", params={"field": "total", "max": 100}))
    assert sim["changed_count"] == 1 and sim["changed"][0]["before"] == "approved" and sim["changed"][0]["after"] == "rejected"
    assert desk.rules_version() == before and len(desk.rules()) == len(DEFAULT_RULES)


def test_auto_approve_switch(desk, good):
    desk.update_settings({"auto_approve": "false"}, "a")
    assert desk.get_run(desk.submit("a.txt", good, "text/plain", "t"))["status"] == "needs_review"


def test_settings_validation(desk):
    for bad in ({"nope": 1}, {"default_mode": "x"}, {"price_in_per_mtok": "abc"}):
        with pytest.raises(DeskError):
            desk.update_settings(bad, "a")


def test_stats_export_reset(desk, good):
    desk.submit("a.txt", good, "text/plain", "t")
    desk.submit("b.txt", good.replace(b"Invoice No: ACM-2026-0001\n", b""), "text/plain", "t")
    s = desk.stats()
    assert s["total"] == 2 and s["by_status"]["approved"] == 1 and s["review_queue"] == 1 and s["auto_approve_rate"] == 0.5
    assert "ACM-2026-0001" in desk.export_csv() and desk.export_csv().count("\n") == 2
    desk.reset("a")
    assert desk.stats()["total"] == 0 and len(desk.rules()) == len(DEFAULT_RULES)
