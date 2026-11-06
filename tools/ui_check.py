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


CHECKS = [mixed_direction, review_badge, waking_screen, rule_with_open_limit]

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
