"""Behaviour checks for the portal in a real browser, against a running server. No screenshots.

    py tools/ui_check.py [base_url]        (default http://127.0.0.1:8000; start the server with an empty database)

Exits non-zero with the failing checks listed. tools/e2e.py is the walk-through that also takes screenshots.
"""
import re
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


def review_layout(page: Page) -> None:
    """Review and run detail: the document beside the fields and checks (mirrored in Arabic), failed checks first,
    Approve and Reject on screen while the reviewer scrolls."""
    sign_in(page)
    load_samples(page, ["inv-016.pdf", "inv-089.txt", "inv-084.xml", "inv-003.txt"])  # inv-084 has a changed IBAN: high risk
    for lang in ("en", "ar"):
        page.evaluate(f"localStorage.setItem('id-lang', '{lang}'); location.hash = '#/review'; location.reload()")
        page.wait_for_selector(".why .ck")
        box = page.evaluate("""() => { const d = document.querySelector('.rq-detail .doc-pane').getBoundingClientRect(),
            s = document.querySelector('.rq-detail .run-side').getBoundingClientRect(); return { dl: d.left, dr: d.right, sl: s.left, sr: s.right, dt: d.top, st: s.top }; }""")
        beside = box["dr"] <= box["sl"] + 1 if lang == "en" else box["sr"] <= box["dl"] + 1
        check(f"review: document and fields side by side, document first in reading order ({lang})", beside and abs(box["dt"] - box["st"]) < 4, str(box))
        check(f"review: failed checks come first ({lang})", "ck-fail" in page.locator(".why .ck").first.get_attribute("class"))
        for where in ("top", "bottom"):
            if where == "bottom":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                page.wait_for_timeout(200)
            on_screen = page.evaluate("""() => [...document.querySelectorAll('.decide .btn')].slice(0, 2).every(b => {
                const r = b.getBoundingClientRect(); return r.top >= 0 && r.bottom <= innerHeight; })""")
            check(f"review: Approve and Reject on screen at the {where} of the page ({lang})", on_screen)
        check(f"review: shortcuts shown beside the decision ({lang})", page.locator(".decide .rq-keys kbd").count() == 4)
        rows = page.evaluate("""() => [...document.querySelectorAll('.rq-item')].map(b => ({
            top: b.querySelector('.rq-top').getBoundingClientRect().height, sub: b.querySelector('.rq-sub').getBoundingClientRect().height, end: Math.round(document.dir === 'rtl' ? b.querySelector('.rq-amt').getBoundingClientRect().left
                : b.querySelector('.rq-amt').getBoundingClientRect().right) }))""")
        check(f"queue: every invoice takes two lines, neither wraps ({lang})", bool(rows) and all(r["top"] <= 26 and r["sub"] <= 22 for r in rows), str(rows))
        check(f"queue: amounts line up at the row end ({lang})", len({r["end"] for r in rows}) == 1, str(rows))
        check(f"queue: the high-risk invoice is marked in the list ({lang})", page.locator(".rq-item.risky .risk-pill").count() >= 1)
    page.evaluate("localStorage.setItem('id-lang', 'en'); location.hash = '#/runs'; location.reload()")
    page.locator("tbody tr", has=page.locator(".s-needs_review")).first.click()
    page.wait_for_selector(".modal .ck")
    check("run detail: document beside the checks", page.locator(".modal.wide .run-split .doc-pane").count() == 1)
    check("run detail: failed checks come first", "ck-fail" in page.locator(".modal .ck").first.get_attribute("class"))
    page.keyboard.press("Escape")
    page.locator("tbody tr", has_text="inv-016.pdf").first.click()
    frame = page.locator(".modal .doc iframe")
    expect(frame).to_be_visible()
    check("run detail: a PDF opens at the pane width, without the page sidebar",
          frame.get_attribute("src").endswith("#navpanes=0&view=FitH"), frame.get_attribute("src"))


def reasons_in_arabic(page: Page) -> None:
    """The reasons under failed checks and the vendor match explanation are in Arabic when the portal is, with
    numbers, IBANs and names kept in their own direction; in English they are shown exactly as the server wrote them."""
    sign_in(page)
    load_samples(page, ["inv-084.xml", "inv-003.txt", "inv-016.pdf", "inv-089.txt"])
    for lang in ("ar", "en"):
        page.evaluate(f"localStorage.setItem('id-lang', '{lang}'); location.hash = '#/review'; location.reload()")
        page.wait_for_selector(".why .ck")
        texts = []
        for i in range(page.locator(".rq-item").count()):
            page.locator(".rq-item").nth(i).click()
            page.wait_for_timeout(300)
            texts += page.evaluate("() => [...document.querySelectorAll('.ck-why, .vm-why')].map(e => e.textContent)")
        arabic = [t for t in texts if re.search("[؀-ۿ]", t)]
        if lang == "ar":
            check("reasons: every reason in the review queue is in Arabic (ar)", bool(texts) and len(arabic) == len(texts),
                  str([t for t in texts if t not in arabic]))
            check("reasons: values inside an Arabic reason keep their own direction (ar)", any("⁨" in t for t in texts))
        else:
            check("reasons: shown as the server wrote them (en)", bool(texts) and not any("⁨" in t for t in texts), str(texts[:3]))


def dashboard_layout(page: Page) -> None:
    """Dashboard: a greeting that says what needs a person; four figures; the headline share before the status bar;
    invoices per day as stacked areas whose legend hides a series and whose columns show a day; a single busy day on a
    scale with a whole-number halfway mark; the period switch changes the window and is remembered."""
    sign_in(page)
    load_samples(page, ["inv-003.txt", "inv-016.pdf", "inv-089.txt"])
    page.evaluate("localStorage.setItem('id-period', '7'); location.hash = '#/dashboard'; location.reload()")
    page.wait_for_selector(".oc-plot")
    check("dashboard: greeting names the signed-in user", "demo-admin" in page.locator(".greet h1").inner_text())
    line = page.locator(".greet-line").inner_text()
    check("dashboard: greeting says what needs a person", "need" in line or "Nothing is waiting" in line, line)
    check("dashboard: four figure tiles", page.locator(".tile").count() == 4)
    order = page.evaluate("""() => { const h = document.querySelector('.headline'), s = document.querySelector('.strip');
        return !!h && !!s && (h.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING) > 0; }""")
    check("dashboard: headline figure comes before the status bar", order)
    check("dashboard: one area per outcome", page.locator(".oc-area").count() == 4)
    top, mid = page.locator(".dc-tick.top").inner_text(), page.locator(".dc-tick.mid").inner_text()
    check("dashboard: scale has a whole-number halfway mark", top == "4" and mid == "2", f"{top} / {mid}")
    page.locator(".oc-key").first.click()
    check("dashboard: the legend hides a series", page.locator(".oc-area").count() == 3
          and page.locator(".oc-key").first.get_attribute("aria-pressed") == "false")
    page.locator(".oc-key").first.click()
    page.locator(".oc-cols > div").last.hover()
    expect(page.locator(".oc-tip")).to_be_visible()
    check("dashboard: a day shows its counts", "Approved automatically" in page.locator(".oc-tip").inner_text())
    check("dashboard: 7 days drawn", page.locator(".oc-cols > div").count() == 7)
    seg = page.locator(".page-head .seg").first.locator("button")
    check("dashboard: period switch offers Today, 7, 30 and 90 days", seg.count() == 4 and seg.nth(0).inner_text() == "Today")
    seg.nth(0).click()
    expect(page.locator(".oc-cols > div")).to_have_count(24)
    seg.nth(2).click()
    expect(page.locator(".oc-cols > div")).to_have_count(30)
    check("dashboard: period is remembered", page.evaluate("localStorage.getItem('id-period')") == "30")
    check("dashboard: oldest waiting list is there", page.get_by_role("heading", name="Oldest waiting").count() == 1)
    check("dashboard: waiting list opens an invoice", page.locator(".wl li").count() >= 1)
    page.locator(".wl li .btn").first.click()
    expect(page.locator(".rq")).to_be_visible()
    check("dashboard: Open goes to the review queue", page.evaluate("location.hash").startswith("#/review/"))


def runs_sorting(page: Page) -> None:
    """Runs: headings sort the rows, say which way with aria-sort, and keep names in their own direction."""
    sign_in(page)
    load_samples(page, ["inv-003.txt", "inv-013.txt", "inv-016.pdf", "inv-089.txt"])
    page.evaluate("location.hash = '#/runs'; location.reload()")
    page.wait_for_selector("tbody tr")
    totals = lambda: page.evaluate("""() => [...document.querySelectorAll('tbody tr td:nth-child(5)')].map(td =>
        parseFloat(td.textContent.replace(/[^0-9.]/g, '')) || 0)""")  # noqa: E731
    head = page.locator("th", has=page.get_by_role("button", name="Total"))
    head.get_by_role("button").click()
    first = totals()
    check("runs: Total sorts largest first", first == sorted(first, reverse=True), str(first))
    check("runs: the sorted heading says so", head.get_attribute("aria-sort") == "descending")
    head.get_by_role("button").click()
    check("runs: a second press sorts smallest first", totals() == sorted(first), str(totals()))
    check("runs: the other headings are not marked sorted", page.locator("th[aria-sort]").count() == 1)
    page.get_by_role("button", name="Seller").click()
    dirs = page.evaluate("""() => [...document.querySelectorAll('tbody tr td:nth-child(4) .cell-text')].map(e => [e.textContent, getComputedStyle(e).direction])""")
    arabic_rtl = [d for n, d in dirs if any("؀" <= ch <= "ۿ" for ch in n)]
    check("runs: Arabic seller names stay right-to-left after sorting", bool(arabic_rtl) and all(d == "rtl" for d in arabic_rtl), str(dirs))


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


def xml_reads_as_an_invoice(page: Page) -> None:
    """A UBL XML invoice is shown as an invoice (parties, lines, totals, IBAN), not as XML. The source is behind a
    closed "Show source XML" toggle; opened, it is indented and left to right. Checked in Arabic and English."""
    sign_in(page, lang="ar")
    load_samples(page, ["inv-084.xml"])
    for lang in ("ar", "en"):
        page.evaluate(f"localStorage.setItem('id-lang', '{lang}'); location.hash = '#/runs'; location.reload()")
        page.locator("tbody tr").first.click()
        inv = page.locator(".modal .doc .inv")
        expect(inv).to_be_visible()
        check(f"XML: invoice view shows number, seller, lines and total ({lang})",
              "GHC-2026-0184" in inv.inner_text() and "Gulf Horizon Consulting" in inv.inner_text()
              and inv.locator(".inv-lines tbody tr").count() >= 1 and "713.28" in inv.locator(".inv-total").inner_text())
        check(f"XML: IBAN shown in groups, left to right ({lang})",
              inv.locator(".inv-pay bdi").first.evaluate("e => e.textContent.startsWith('SA15 0523') && getComputedStyle(e).direction === 'ltr'"))
        check(f"XML: invoice view follows the page direction ({lang})",
              inv.evaluate("e => getComputedStyle(e).direction") == ("rtl" if lang == "ar" else "ltr"))
        check(f"XML: no source visible until asked ({lang})", not page.locator(".modal .doc pre.xml").is_visible()
              and "<cbc:" not in inv.inner_text())
        page.locator(".inv-src summary").click()
        pre = page.locator(".modal .doc pre.xml")
        expect(pre).to_be_visible()
        page.wait_for_function("document.querySelector('.modal .doc pre.xml').textContent.includes('</Invoice>')")
        lines = pre.inner_text().splitlines()
        check(f"XML: source is indented, one element a line ({lang})", len(lines) > 40 and any(ln.startswith("    <cbc:") for ln in lines), lines[:3])
        check(f"XML: source reads left to right ({lang})", pre.evaluate("e => getComputedStyle(e).direction") == "ltr")


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


def demo_start(page: Page) -> None:
    """An empty database greets a first visitor in Arabic; the sample set gives a mix, not a wall of red; the source
    filter and the demo note are there; Settings resets the demo after a confirm step."""
    sign_in(page, lang="ar")
    api(page, "POST", "/admin/reset", {})
    page.reload()
    expect(page.locator(".welcome")).to_be_visible()
    check("Demo note is shown", page.locator(".demo-note").count() == 1)
    check("Demo note says the history is spread over 30 days", "30" in page.locator(".demo-note").inner_text())
    check("Welcome card reads right-to-left", page.locator(".welcome").evaluate("e => getComputedStyle(e).direction") == "rtl")
    page.get_by_role("button", name="تحميل فواتير نموذجية").click()
    expect(page.locator(".strip")).to_be_visible(timeout=20000)
    page.wait_for_function("document.querySelectorAll('.hbar.bad').length > 0", timeout=20000)
    for _ in range(120):  # the sample history is read one invoice at a time
        s = api(page, "GET", "/stats", None)["body"]
        if s["by_status"]["queued"] + s["by_status"]["processing"] == 0:
            break
        time.sleep(0.5)
    b = s["by_status"]
    check("Sample set is a mix with a history", b["needs_review"] == 6 and b["approved"] > 11 and b["approved_human"] > 0
          and b["rejected"] + b["rejected_human"] > 3, b)
    check("Sample history covers 30 days", api(page, "GET", "/stats?days=30", None)["body"]["period"]["current"]["received"] == s["total"])
    check("Top rejection reasons are listed", page.locator(".hbar.bad").count() >= 2)
    check("Activity feed lists what people did", page.locator(".feed li").count() >= 2)
    page.locator(".page-head .seg").last.locator("button").nth(1).click()
    expect(page.locator("main .empty h3")).to_contain_text("لا توجد عمليات تقييم", timeout=10000)
    check("Evaluation source starts empty", page.locator(".strip").count() == 0)
    page.evaluate("location.hash = '#/settings'")
    page.get_by_role("button", name="إعادة ضبط البيانات التجريبية").click()
    expect(page.locator(".modal")).to_be_visible()
    page.locator(".modal .btn.danger").click()
    expect(page.locator(".modal")).to_have_count(0)
    check("Reset clears the runs", api(page, "GET", "/stats", None)["body"]["total"] == 0)
    page.evaluate("location.hash = '#/dashboard'")
    expect(page.locator(".welcome")).to_be_visible()


def run_timeline(page: Page) -> None:
    """Run detail: a timeline from received to the reviewer's decision, with the corrected field named, in both languages;
    the technical trace folds away."""
    sign_in(page)
    load_samples(page, ["inv-003.txt", "inv-013.txt", "inv-016.pdf", "inv-089.txt"])
    waiting = api(page, "GET", "/runs?status=needs_review")["body"]["items"]
    check("timeline: a sample waits for review", bool(waiting))
    if not waiting:
        return
    rid = waiting[0]["id"]
    api(page, "POST", f"/runs/{rid}/review", {"decision": "approve", "note": "checked by phone", "edits": {"invoice_number": "UI-CHECK-1"}})
    page.evaluate(f"location.hash = '#/runs/{rid}'; location.reload()")
    page.wait_for_selector(".tl li")
    items = page.locator(".tl li")
    # names sit in direction isolates (U+2068 ... U+2069); drop them to compare the words
    text = [items.nth(i).inner_text().replace("⁨", "").replace("⁩", "") for i in range(items.count())]
    check("timeline: starts with received and ends with the reviewer", text[0].startswith("Received from") and "Approved by demo-admin" in text[-1], str(text))
    check("timeline: says which reader and which rules version", any("Read by" in x for x in text) and any("rules version" in x for x in text), str(text))
    check("timeline: names the corrected field", "Corrected: Invoice number" in text[-1], text[-1])
    check("timeline: steps carry a time", page.locator(".tl li time[datetime]").count() == items.count())
    check("timeline: the technical trace is folded", page.locator("details.trace-more").get_attribute("open") is None)
    page.evaluate(f"localStorage.setItem('id-lang', 'ar'); location.hash = '#/runs/{rid}'; location.reload()")
    page.wait_for_selector(".tl li")
    rail = page.evaluate("""() => { const l = document.querySelector('.tl li'), s = getComputedStyle(l, '::before');
        return [getComputedStyle(l).direction, parseFloat(s.right), parseFloat(s.left)]; }""")
    check("timeline: right to left in Arabic, rail on the right", rail[0] == "rtl" and rail[1] < 0, str(rail))
    last = page.locator(".tl li").last.inner_text()
    check("timeline: Arabic wording", "اعتمدها" in last and "رقم الفاتورة" in last, last)


CHECKS = [mixed_direction, reasons_in_arabic, review_badge, waking_screen, rule_with_open_limit, error_messages, damaged_file, provider_failure, xml_reads_as_an_invoice,
          vendors_and_risk, demo_start, review_layout, dashboard_layout, runs_sorting, run_timeline]

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
