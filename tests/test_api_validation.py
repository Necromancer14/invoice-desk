"""Input validation found missing in the self-audit: every bad request gets a 4xx with a message, never a 500."""
import pytest
from fastapi.testclient import TestClient

from invoice_desk.api import create_app
from invoice_desk.desk import PDF_UNREADABLE, Desk, clean_filename
from conftest import GOOD, TODAY


@pytest.fixture
def c(auth):
    return TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=1000), raise_server_exceptions=False)


@pytest.fixture
def a(c):
    return {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "admin"}).json()["token"]}


def upload(c, h, name="a.txt", blob=GOOD.encode(), ctype="text/plain"):
    return c.post("/api/runs", files={"files": (name, blob, ctype)}, headers=h)


def test_rollback_with_a_bad_version_is_a_400(c, a):
    for v in ("abc", None, -1, 0, [1]):
        r = c.post("/api/rules/rollback", json={"version": v}, headers=a)
        assert r.status_code == 400 and "version" in r.json()["detail"], (v, r.text)
    assert c.post("/api/rules/rollback", json={"version": 999}, headers=a).status_code == 404


def test_list_limits_are_clamped(c, a):
    for i in range(3):
        upload(c, a, f"{i}.txt")
    assert len(c.get("/api/runs?limit=-1", headers=a).json()["items"]) == 1  # clamped to 1, not "everything"
    assert len(c.get("/api/runs?limit=100000", headers=a).json()["items"]) == 3
    assert c.get("/api/runs?offset=-5", headers=a).status_code == 200
    assert c.get("/api/audit?limit=100000000", headers=a).status_code == 200
    assert len(c.get("/api/audit?limit=0", headers=a).json()) == 1


def test_sample_and_reorder_bodies_must_be_lists(c, a):
    r = c.post("/api/samples/submit", json={"files": "inv-001.txt"}, headers=a)
    assert r.status_code == 400 and "list" in r.json()["detail"]
    r = c.put("/api/rules/reorder", json={"keys": "required"}, headers=a)
    assert r.status_code == 400 and "list" in r.json()["detail"]


def test_long_text_is_refused_with_a_message(c, a):
    rule = dict(name="x" * 121, type="duplicate", severity="review")
    r = c.post("/api/rules", json=rule, headers=a)
    assert r.status_code == 400 and "120" in r.json()["detail"]
    r = c.post("/api/rules", json=dict(rule, name="ok", message="m" * 301), headers=a)
    assert r.status_code == 400 and "300" in r.json()["detail"]
    r = c.post("/api/rules", json=dict(rule, name="ok", note="n" * 501), headers=a)
    assert r.status_code == 400 and "500" in r.json()["detail"]
    r = c.post("/api/rules", json=dict(rule, name="ok", params=[1, 2]), headers=a)
    assert r.status_code in (400, 422)
    rid = upload(c, a, blob=GOOD.replace("Invoice No: ACM-2026-0001\n", "").encode()).json()["ids"][0]
    r = c.post(f"/api/runs/{rid}/review", json={"decision": "reject", "note": "n" * 2001}, headers=a)
    assert r.status_code == 400 and "2000" in r.json()["detail"]


def test_file_names_are_cleaned():
    assert clean_filename("..\\..\\x\"\r\nInjected.txt") == 'x"Injected.txt'
    assert clean_filename("/etc/passwd") == "passwd"
    assert clean_filename("") == "invoice.txt" and len(clean_filename("a" * 500)) == 120


def test_uploads_over_5_mb_are_refused(c, a):
    r = upload(c, a, "big.txt", b"a" * (5 * 1024 * 1024 + 1))
    assert r.status_code == 413 and "5 MB" in r.json()["detail"]


def test_wrong_type_and_empty_files_are_refused(c, a):
    assert upload(c, a, "x.exe", b"MZ", "application/octet-stream").status_code == 415
    assert upload(c, a, "e.txt", b"").status_code == 400


def test_a_damaged_pdf_fails_with_a_plain_message(c, a):
    rid = upload(c, a, "broken.pdf", b"%PDF-1.4 not really a pdf", "application/pdf").json()["ids"][0]
    run = c.get(f"/api/runs/{rid}", headers=a).json()
    assert run["status"] == "failed" and run["error"] == PDF_UNREADABLE
    assert any(s["step"] == "error" and "Pdf" in s["detail"] for s in run["trace"])  # the technical detail is kept


def test_rate_limit_answers_429_with_a_message(auth):
    c = TestClient(create_app(Desk(":memory:", today=TODAY, sync=True), auth, rate_limit=2))
    h = {"Authorization": "Bearer " + c.post("/api/auth/demo", json={"role": "reviewer"}).json()["token"]}
    codes = [upload(c, h, f"{i}.txt").status_code for i in range(3)]
    assert codes[:2] == [200, 200] and codes[2] == 429


@pytest.mark.parametrize("name, blob, ctype", [
    ("program.txt", b"MZ\x90\x00\x03\x00\x00\x00", "text/plain"),      # a program renamed to .txt
    ("fake.png", b"%PDF-1.4 hello", "image/png"),                      # a PDF claiming to be a PNG
    ("fake.pdf", b"just some text", "application/pdf"),
    ("fake.jpg", b"\x89PNG\r\n\x1a\nxxxx", "image/jpeg"),
])
def test_contents_must_match_the_claimed_type(c, a, name, blob, ctype):
    r = upload(c, a, name, blob, ctype)
    assert r.status_code == 415 and "does not look like" in r.json()["detail"], r.text


def test_real_files_of_each_type_are_accepted(c, a):
    from invoice_desk.evaluation import SAMPLES
    for name in ("inv-001.png", "inv-004.pdf", "inv-003.txt"):
        assert upload(c, a, name, (SAMPLES / name).read_bytes(), "").status_code == 200, name
