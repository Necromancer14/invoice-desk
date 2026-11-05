import pytest
from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.desk import Desk
from conftest import GOOD, TODAY


@pytest.fixture
def client(auth):
    return TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=1000))


def H(client, role):
    t = client.post("/api/auth/demo", json={"role": role}).json()["token"]
    return {"Authorization": f"Bearer {t}"}


def test_requires_login(client):
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", headers={"Authorization": "Bearer junk.junk"}).status_code == 401


def test_roles(client):
    v, r, a = H(client, "viewer"), H(client, "reviewer"), H(client, "admin")
    f = {"files": ("a.txt", GOOD, "text/plain")}
    assert client.post("/api/runs", files=f, headers=v).status_code == 403
    assert client.post("/api/runs", files=f, headers=r).status_code == 200
    rule = dict(name="x", type="duplicate", severity="review")
    assert client.post("/api/rules", json=rule, headers=r).status_code == 403
    assert client.post("/api/rules", json=rule, headers=a).status_code == 200
    assert client.put("/api/settings", json={"auto_approve": "true"}, headers=r).status_code == 403
    assert client.post("/api/admin/reset", headers=r).status_code == 403


def test_upload_review_flow(client):
    r = H(client, "reviewer")
    ids = client.post("/api/runs", files={"files": ("a.txt", GOOD.replace("Invoice No: ACM-2026-0001\n", ""), "text/plain")}, headers=r).json()["ids"]
    run = client.get(f"/api/runs/{ids[0]}", headers=r).json()
    assert run["status"] == "needs_review"
    assert client.get("/api/review/next", headers=r).json()["id"] == ids[0]
    assert client.get(f"/api/runs/{ids[0]}/file", headers=r).content.startswith(b"TAX INVOICE")
    bad = client.post(f"/api/runs/{ids[0]}/review", json=dict(decision="reject"), headers=r)
    assert bad.status_code == 400 and "note" in bad.json()["detail"]
    ok = client.post(f"/api/runs/{ids[0]}/review", json=dict(decision="approve", edits={"invoice_number": "Z-1"}), headers=r)
    assert ok.json()["status"] == "approved_human"
    assert client.post(f"/api/runs/{ids[0]}/review", json=dict(decision="approve"), headers=r).status_code == 409
    assert client.get("/api/stats", headers=r).json()["human_corrected"] == 1


def test_rules_api_and_simulate(client):
    a = H(client, "admin")
    types = client.get("/api/rules/types", headers=a).json()
    assert "expression" in types["types"] and "fn" not in types["types"]["expression"]
    client.post("/api/runs", files={"files": ("a.txt", GOOD, "text/plain")}, headers=a)
    sim = client.post("/api/rules/simulate", json={"rule": dict(name="t", type="amount_limit", severity="reject", params={"field": "total", "max": 1})}, headers=a).json()
    assert sim["changed_count"] == 1
    bad = client.post("/api/rules", json=dict(name="x", type="expression", severity="review", params={"expr": "open('f')"}), headers=a)
    assert bad.status_code == 400
    v = client.get("/api/rules/versions", headers=a).json()
    assert client.post("/api/rules/rollback", json={"version": v[-1]["version"]}, headers=a).status_code == 200
    assert client.get("/api/audit", headers=a).json()


def test_upload_limits(client):
    r = H(client, "reviewer")
    assert client.post("/api/runs", files={"files": ("a.exe", b"x", "application/x-msdownload")}, headers=r).status_code == 415
    assert client.post("/api/runs", files=[("files", (f"{i}.txt", b"x", "text/plain")) for i in range(21)], headers=r).status_code == 400


def test_rate_limit(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=3))
    r = H(c, "reviewer")
    codes = [c.post("/api/runs", files={"files": ("a.txt", GOOD, "text/plain")}, headers=r).status_code for _ in range(5)]
    assert codes[:3] == [200] * 3 and 429 in codes[3:]


def test_login_and_demo_off(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth))
    assert c.post("/api/auth/login", json={"name": "boss", "password": "pw"}).json()["role"] == "admin"
    assert c.post("/api/auth/login", json={"name": "boss", "password": "no"}).status_code == 401
    auth.demo = False
    assert c.post("/api/auth/demo", json={"role": "admin"}).status_code == 403


def test_samples_and_csv(client):
    r = H(client, "reviewer")
    lst = client.get("/api/samples", headers=r).json()
    assert len(lst) == 60 and client.get(f"/api/samples/{lst[2]['file']}", headers=r).status_code == 200
    assert client.get("/api/samples/..%2Fsecret", headers=r).status_code == 404
    ids = client.post("/api/samples/submit", json={"files": [x["file"] for x in lst if x["format"] == "txt"][:3]}, headers=r).json()["ids"]
    assert len(ids) == 3 and "text/csv" in client.get("/api/export.csv", headers=r).headers["content-type"]
    assert client.post("/api/samples/submit", json={"files": ["nope.txt"]}, headers=r).status_code == 404


def test_ai_mode_requires_provider_headers(client):
    r = H(client, "reviewer")
    resp = client.post("/api/runs", files={"files": ("a.txt", GOOD, "text/plain")}, data={"mode": "ai"}, headers=r)
    assert resp.status_code == 400 and "provider" in resp.json()["detail"]


def test_provider_list_and_test_endpoint_without_key(client):
    r = H(client, "reviewer")
    assert client.get("/api/llm/providers", headers=r).json()[0]["id"] == "gemini"
    resp = client.post("/api/llm/test", headers={**r, "X-LLM-Provider": "gemini"})
    assert resp.status_code == 400 and "key" in resp.json()["detail"]


def test_llm_headers_reach_the_pipeline_and_are_not_stored(auth):
    from invoice_desk.extractors import RuleBasedExtractor
    seen = {}

    def factory(mode, llm):
        seen.update(mode=mode, llm=llm)
        return RuleBasedExtractor()
    d = Desk(":memory:", today=TODAY, sync=True, extractor_factory=factory)
    c = TestClient(create_app(d, auth))
    h = {**H(c, "reviewer"), "X-LLM-Provider": "gemini", "X-LLM-Key": "AIza-secret", "X-LLM-Model": "gemini-3.8-flash"}
    assert c.post("/api/runs", files={"files": ("a.txt", GOOD, "text/plain")}, data={"mode": "ai"}, headers=h).status_code == 200
    assert seen["mode"] == "ai" and seen["llm"] == {"provider": "gemini", "key": "AIza-secret", "model": "gemini-3.8-flash"}
    dump = " ".join(str(r) for t in ("runs", "audit", "settings") for r in d.db.all(f"SELECT * FROM {t}"))
    assert "AIza-secret" not in dump


def _needs_review(n: int) -> bytes:
    """An invoice with no invoice number: the required-fields rule sends it to review."""
    return GOOD.replace("Invoice No: ACM-2026-0001\n", "").replace("Beta Foods", f"Buyer {n}").encode()


def test_review_queue_lists_waiting_runs_oldest_first(client):
    r = H(client, "reviewer")
    clean = client.post("/api/runs", files={"files": ("clean.txt", GOOD, "text/plain")}, headers=r).json()["ids"][0]
    waiting = [client.post("/api/runs", files={"files": (f"w{i}.txt", _needs_review(i), "text/plain")}, headers=r).json()["ids"][0]
               for i in range(3)]
    bad_vat = GOOD.replace("300000000000003", "12345")
    rejected = client.post("/api/runs", files={"files": ("bad.txt", bad_vat, "text/plain")}, headers=r).json()["ids"][0]
    assert client.get(f"/api/runs/{clean}", headers=r).json()["status"] == "approved"
    assert client.get(f"/api/runs/{rejected}", headers=r).json()["status"] == "rejected"

    q = client.get("/api/review/queue", headers=r).json()
    assert [x["id"] for x in q] == waiting
    first = q[0]
    assert set(first) == {"id", "filename", "created_at", "seller", "invoice_number", "total", "currency", "failed_checks"}
    assert first["filename"] == "w0.txt" and first["seller"] == "Acme Trading" and first["invoice_number"] is None
    assert first["total"] == 1150.0 and first["currency"] == "SAR" and first["failed_checks"] == 2  # required fields + low confidence


def test_review_queue_roles(client):
    assert client.get("/api/review/queue").status_code == 401
    for role in ("viewer", "reviewer", "admin"):
        assert client.get("/api/review/queue", headers=H(client, role)).status_code == 200


def test_review_queue_updates_after_decisions(client):
    r = H(client, "reviewer")
    ids = [client.post("/api/runs", files={"files": (f"w{i}.txt", _needs_review(i), "text/plain")}, headers=r).json()["ids"][0]
           for i in range(3)]
    client.post(f"/api/runs/{ids[1]}/review", json=dict(decision="approve", edits={"invoice_number": "Z-9"}), headers=r)
    assert [x["id"] for x in client.get("/api/review/queue", headers=r).json()] == [ids[0], ids[2]]
    client.post(f"/api/runs/{ids[0]}/review", json=dict(decision="reject", note="not ours"), headers=r)
    assert [x["id"] for x in client.get("/api/review/queue", headers=r).json()] == [ids[2]]
    client.post(f"/api/runs/{ids[2]}/review", json=dict(decision="approve", edits={"invoice_number": "Z-10"}), headers=r)
    assert client.get("/api/review/queue", headers=r).json() == []
