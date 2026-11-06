"""Behaviour checks for the portal in a real browser, against a running server. No screenshots.

    py tools/ui_check.py [base_url]        (default http://127.0.0.1:8000; start the server with an empty database)

Exits non-zero with the failing checks listed. tools/e2e.py is the walk-through that also takes screenshots.
"""
import sys
import time

from playwright.sync_api import Page, expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def sign_in(page: Page, role: str = "admin", lang: str = "en") -> None:
    page.goto(BASE)
    page.evaluate("([l]) => { localStorage.setItem('id-lang', l); localStorage.setItem('id-theme', 'light'); }", [lang])
    page.goto(BASE)
    page.locator(".roles button").nth({"admin": 0, "reviewer": 1, "viewer": 2}[role]).click()
    expect(page.locator(".nav")).to_be_visible()


def api(page: Page, method: str, path: str, body=None):
    """Call the API with the signed-in token, from inside the page."""
    return page.evaluate("""async ([m, p, b]) => {
        const r = await fetch('/api' + p, { method: m, headers: { 'Content-Type': 'application/json',
            Authorization: 'Bearer ' + localStorage.getItem('id-token') }, body: b === null ? undefined : JSON.stringify(b) });
        return { status: r.status, body: await r.json().catch(() => null) };
    }""", [method, path, body])


def load_samples(page: Page, files: list[str]) -> None:
    api(page, "POST", "/admin/reset", {})
    api(page, "POST", "/samples/submit", {"files": files})
    page.wait_for_function("""async () => {
        const r = await fetch('/api/stats', { headers: { Authorization: 'Bearer ' + localStorage.getItem('id-token') } });
        const s = await r.json(); return s.by_status.queued + s.by_status.processing === 0;
    }""", timeout=20000)


def mixed_direction(page: Page) -> None:
    """An Arabic seller name in the English Runs table keeps right-to-left text but lines up with its column."""
    sign_in(page)
    load_samples(page, ["inv-013.txt", "inv-003.txt"])  # inv-013 has an Arabic seller name
    page.evaluate("location.hash = '#/runs'")
    page.wait_for_selector("tbody tr")
    cells = page.evaluate("""() => [...document.querySelectorAll('tbody tr td:nth-child(4) .cell-text')].map(e => {
        const td = e.closest('td').getBoundingClientRect(), r = e.getBoundingClientRect();
        const range = document.createRange(); range.selectNodeContents(e); const text = range.getBoundingClientRect();
        return { name: e.textContent, dir: getComputedStyle(e).direction, align: getComputedStyle(e).textAlign,
                 gapStart: Math.round(text.left - td.left) };
    })""")
    arabic = [c for c in cells if any("؀" <= ch <= "ۿ" for ch in c["name"])]
    check("Runs table has an Arabic seller name to test with", bool(arabic), str(cells))
    for c in arabic:
        check(f"Arabic name reads right-to-left in the English table ({c['name']})", c["dir"] == "rtl", str(c))
        check("Arabic name starts at the column's left edge, like the heading", c["align"] == "left" and c["gapStart"] <= 20, str(c))
    page.evaluate("localStorage.setItem('id-lang', 'ar'); location.reload()")
    page.wait_for_selector("tbody tr")
    english = page.evaluate("""() => [...document.querySelectorAll('tbody tr td:nth-child(4) .cell-text')]
        .filter(e => /[A-Za-z]/.test(e.textContent)).map(e => ({ dir: getComputedStyle(e).direction, align: getComputedStyle(e).textAlign }))""")
    check("English name reads left-to-right in the Arabic table, aligned right", bool(english) and all(e["dir"] == "ltr" and e["align"] == "right" for e in english), str(english))


def review_badge(page: Page) -> None:
    """The sidebar count drops as soon as an invoice is decided, even when the server is slow to report it."""
    sign_in(page)
    load_samples(page, ["inv-006.txt", "inv-012.txt", "inv-019.txt", "inv-009.txt"])
    page.evaluate("location.hash = '#/review'")
    page.wait_for_selector("#reject-note")
    badge = "document.querySelector('.nav .count')?.textContent || '0'"
    listed = page.locator(".rq-item").count()
    page.wait_for_function(f"({badge}) === '{listed}'", timeout=5000)
    check("badge matches the review list", page.evaluate(badge) == str(listed), f"badge {page.evaluate(badge)}, list {listed}")

    def slow(route):  # every stats answer now takes 2 s
        time.sleep(2)
        route.continue_()
    page.route("**/api/stats", slow)
    page.keyboard.press("a")
    page.wait_for_selector(".toast")
    after = page.evaluate(badge)
    check("badge drops at once after approving, before the slow server answers", after == str(listed - 1), f"was {listed}, now {after}")
    page.wait_for_timeout(2500)
    check("badge still right once the server answers", page.evaluate(badge) == str(listed - 1), page.evaluate(badge))
    page.unroute("**/api/stats")


def waking_screen(page: Page) -> None:
    """While /api/health does not answer, a 'waking up' screen shows in the chosen language, then sign-in follows."""
    page.goto(BASE)
    page.evaluate("localStorage.removeItem('id-token'); localStorage.setItem('id-lang', 'ar')")
    asleep = {"on": True}
    page.route("**/api/health", lambda route: route.fulfill(status=503, body="waking") if asleep["on"] else route.continue_())
    page.goto(BASE)
    title = page.get_by_role("heading", name="جارٍ تشغيل العرض التجريبي")
    expect(title).to_be_visible(timeout=6000)
    check("waking screen shows in Arabic after a few seconds", title.is_visible())
    check("waking screen is announced politely to screen readers", page.locator(".login .panel[role=status][aria-live=polite]").count() == 1)
    check("waking screen is right-to-left", page.evaluate("document.documentElement.dir") == "rtl")
    asleep["on"] = False
    expect(page.locator(".roles")).to_be_visible(timeout=8000)
    check("sign-in appears by itself once the server answers", page.locator(".roles").is_visible())

    # give up after 90 s: run the page on a fake clock and jump ahead
    page.unroute("**/api/health")
    page.route("**/api/health", lambda route: route.fulfill(status=503, body="waking"))
    page.clock.install()
    page.evaluate("localStorage.setItem('id-lang', 'en')")
    page.goto(BASE)
    page.clock.run_for(4000)
    expect(page.get_by_role("heading", name="Waking up the demo")).to_be_visible()
    for _ in range(40):  # each pass lets the 3 s retry wait and a request go round
        page.clock.run_for(3000)
        if page.get_by_role("heading", name="The demo did not wake up").count():
            break
    failed = page.get_by_role("heading", name="The demo did not wake up")
    check("after 90 seconds it says the demo did not wake up", failed.count() == 1)
    page.unroute("**/api/health")
    page.get_by_role("button", name="Try again").click()
    page.clock.run_for(1000)
    expect(page.locator(".roles")).to_be_visible(timeout=5000)
    check("Try again reaches sign-in once the server is up", page.locator(".roles").is_visible())


def rule_with_open_limit(page: Page) -> None:
    """The new 'Total is not negative' rule has no upper limit: the editor shows that as an empty box and saves it."""
    sign_in(page)
    api(page, "POST", "/admin/reset", {})
    page.evaluate("location.hash = '#/rules'")
    card = page.locator(".rulecard", has_text="Total is not negative")
    expect(card).to_be_visible()
    card.get_by_role("button", name="Edit").click()
    boxes = page.locator(".modal input[type=number]")
    values = [boxes.nth(i).input_value() for i in range(boxes.count())]
    check("min shows 0 and max shows empty, not 'null'", values == ["0", ""], str(values))
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator(".modal")).to_have_count(0)
    saved = api(page, "GET", "/rules")["body"]["rules"]
    rule = next(r for r in saved if r["key"] == "total-not-negative")
    check("saving keeps the open upper limit", rule["params"].get("max") is None and rule["params"].get("min") == 0, str(rule["params"]))


def error_messages(page: Page) -> None:
    """Rate limit, a busy server, no connection, a hung request and a damaged file each give a plain message, in both languages."""
    sign_in(page)
    api(page, "POST", "/admin/reset", {})
    cases = [
        ("429 rate limit", lambda r: r.fulfill(status=429, json={"detail": "too many requests, slow down a little"}),
         "Too many requests. Wait a minute and try again.", "طلبات كثيرة جدًا. انتظر دقيقة ثم حاول مرة أخرى."),
        ("503 while starting", lambda r: r.fulfill(status=503, body="Service Unavailable"),
         "The server is starting or busy. Try again in a moment.", "الخادم قيد التشغيل أو مشغول. حاول مرة أخرى بعد قليل."),
        ("500 with no detail", lambda r: r.fulfill(status=500, body="Internal Server Error"),
         "Something went wrong on the server. Try again, and if it keeps happening, check the server log.", "حدث خطأ في الخادم."),
        ("no connection", lambda r: r.abort("internetdisconnected"),
         "Cannot reach the server. Check your connection and try again.", "تعذّر الاتصال بالخادم."),
    ]
    for lang in ("en", "ar"):
        page.evaluate(f"localStorage.setItem('id-lang', '{lang}')")
        for name, handler, en, ar in cases:
            page.route("**/api/runs?*", handler)
            page.evaluate("location.hash = '#/dashboard'")
            page.evaluate("location.hash = '#/runs'; location.reload()")
            alert = page.locator(".notice.err[role=alert]")
            expect(alert).to_be_visible(timeout=8000)
            text = alert.inner_text()
            want = en if lang == "en" else ar
            check(f"{name} ({lang}): plain message", want in text, text)
            page.unroute("**/api/runs?*")

    # a request that never answers stops after 30 s with a message (on a fake clock, so the check is quick)
    page.evaluate("localStorage.setItem('id-lang', 'en')")
    page.clock.install()
    page.route("**/api/audit?*", lambda route: None)  # never answers
    page.evaluate("location.hash = '#/audit'; location.reload()")
    page.wait_for_selector(".seg")
    page.clock.run_for(31_000)
    alert = page.locator(".notice.err[role=alert]")
    expect(alert).to_be_visible(timeout=5000)
    check("hung request: times out with a message", "took too long" in alert.inner_text(), alert.inner_text())
    page.unroute_all(behavior="ignoreErrors")  # let go of the request left hanging on purpose


def damaged_file(page: Page) -> None:
    """A damaged PDF and a program renamed to .txt are explained in plain words."""
    sign_in(page)
    api(page, "POST", "/admin/reset", {})
    page.evaluate("location.hash = '#/intake'")
    page.locator("input[type=file]").set_input_files([
        {"name": "broken.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 not really a pdf"}])
    page.get_by_role("button", name="Process 1 file").click()
    page.wait_for_selector("tbody tr")
    page.wait_for_function("document.querySelector('tbody tr .pill')?.textContent.includes('Failed')", timeout=10000)
    page.locator("tbody tr").first.click()
    note = page.locator(".modal .notice.err")
    expect(note).to_be_visible()
    check("damaged PDF says it could not be opened", "could not be opened" in note.inner_text(), note.inner_text())
    page.keyboard.press("Escape")
    page.evaluate("location.hash = '#/intake'")
    page.locator("input[type=file]").set_input_files([
        {"name": "program.txt", "mimeType": "text/plain", "buffer": b"MZ\x90\x00\x03\x00"}])
    page.get_by_role("button", name="Process 1 file").click()
    alert = page.locator(".notice.err[role=alert]")
    expect(alert).to_be_visible()
    check("program renamed to .txt is refused with its name", "program.txt does not look like a text file" in alert.inner_text(), alert.inner_text())


def provider_failure(page: Page) -> None:
    """When the AI provider cannot be reached, the connection test says so, rather than blaming our server."""
    sign_in(page)
    page.evaluate("sessionStorage.setItem('id-llm-key-gemini', 'not-a-real-key'); localStorage.setItem('id-llm-provider', 'gemini')")
    page.route("**/api/llm/test", lambda r: r.fulfill(status=502, json={"detail": "could not reach the provider: ConnectError"}))
    page.evaluate("location.hash = '#/settings'; location.reload()")
    page.get_by_role("button", name="Save and test connection").click()
    msg = page.locator(".notice.err[role=status]")
    expect(msg).to_be_visible()
    check("provider failure shows the provider's problem", "could not reach the provider" in msg.inner_text(), msg.inner_text())
    page.unroute("**/api/llm/test")
    page.evaluate("sessionStorage.clear()")


def xml_is_indented(page: Page) -> None:
    """A UBL XML invoice shows indented, one element per line, left-to-right even in Arabic."""
    sign_in(page, lang="ar")
    load_samples(page, ["inv-073.xml"])
    page.evaluate("location.hash = '#/runs'")
    page.locator("tbody tr").first.click()
    pre = page.locator(".modal .doc pre")
    expect(pre).to_be_visible()
    page.wait_for_function("document.querySelector('.modal .doc pre').textContent.includes('</Invoice>')")
    text = pre.inner_text()
    lines = text.splitlines()
    check("XML is shown on many lines", len(lines) > 40, f"{len(lines)} lines")
    check("XML is indented", any(line.startswith("    <cbc:") for line in lines), lines[:5])
    check("XML reads left-to-right in Arabic", pre.evaluate("e => getComputedStyle(e).direction") == "ltr")


def vendors_and_risk(page: Page) -> None:
    """The Vendors page lists the demo vendor master in Arabic; a changed IBAN is marked high risk in the queue and the
    run detail; a seller can be linked to a vendor in one click; a malformed IBAN is refused with a message."""
    sign_in(page, lang="ar")
    load_samples(page, ["inv-083.txt", "inv-086.txt"])
    page.evaluate("location.hash = '#/vendors'")
    rows = page.locator("table").first.locator("tbody tr")
    expect(rows.first).to_be_visible()
    check("Vendors page lists the vendor master", rows.count() >= 13, rows.count())
    iban = page.locator("table").first.locator("tbody tr td.num bdi").nth(1)
    check("IBAN reads left-to-right in Arabic", iban.evaluate("e => getComputedStyle(e).direction") == "ltr")
    page.get_by_role("button", name="إضافة مورد").click()
    page.locator(".modal input").first.fill("Test Vendor")
    page.locator(".modal input").nth(4).fill("SA00 1234")
    page.locator(".modal .btn.primary").click()
    expect(page.locator(".modal .notice.err")).to_be_visible()
    check("A malformed IBAN is refused with a message", "IBAN" in page.locator(".modal .notice.err").inner_text())
    page.keyboard.press("Escape")
    page.evaluate("location.hash = '#/review'")
    expect(page.locator(".rq-item").first).to_be_visible()
    check("Changed IBAN is marked high risk in the queue", page.locator(".rq-item .risk-pill").count() == 1)
    page.locator(".rq-item", has=page.locator(".risk-pill")).click()
    expect(page.locator(".checks .high-risk")).to_be_visible()
    check("Run detail shows the high-risk check", page.locator(".checks .high-risk .risk-pill").count() == 1)
    check("Run detail shows the PO", page.locator(".po-line").count() == 1)
    page.locator(".rq-item", has_not=page.locator(".risk-pill")).click()
    link = page.get_by_role("button", name="ربط بالمورد").first
    expect(link).to_be_visible()
    link.click()
    expect(page.locator(".vm .pill.s-approved")).to_be_visible()
    check("Link to vendor matches the seller", "اسم مرتبط" in page.locator(".vm").first.inner_text())


CHECKS = [mixed_direction, review_badge, waking_screen, rule_with_open_limit, error_messages, damaged_file, provider_failure, xml_is_indented,
          vendors_and_risk]

if __name__ == "__main__":
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for fn in CHECKS:
            ctx = browser.new_context(viewport={"width": 1360, "height": 860})
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            try:
                fn(page)
            except Exception as exc:  # noqa: BLE001 - a crashed check is a failed check
                check(f"{fn.__name__} ran to the end", False, f"{type(exc).__name__}: {str(exc)[:300]}")
            check(f"{fn.__name__}: no script errors in the page", not errors, "; ".join(errors))
            ctx.close()
        browser.close()
    if failures:
        print(f"\n{len(failures)} failed:", *failures, sep="\n  ")
        sys.exit(1)
    print("\nall UI checks passed")
