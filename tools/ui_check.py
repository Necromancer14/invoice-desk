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


CHECKS = [mixed_direction, review_badge]

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
