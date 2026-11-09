"""Screenshots of every portal page in English and Arabic, light and dark, for design reviews.

    py tools/ui_shots.py OUT_DIR [base_url]      (default http://127.0.0.1:8000; start the server with an empty database)

Resets the demo data, loads the sample invoices (the 20 welcome samples and the 30-day history) and runs the built-in
evaluation, then saves OUT_DIR/<nn>-<page>-<lang>-<theme>.jpg. Used for docs/ui/before and docs/ui/after.
Headless Chromium has no PDF viewer, so a PDF original shows as a blank pane in these shots; in a browser it renders.
"""
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/ui/shots")
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8000"
OUT.mkdir(parents=True, exist_ok=True)
COMBOS = [(lang, theme) for lang in ("en", "ar") for theme in ("light", "dark")]
STEADY = """document.addEventListener('DOMContentLoaded', () => { const s = document.createElement('style');
  s.textContent = '*, *::before, *::after { transition: none !important; animation: none !important; caret-color: transparent !important; } .toast { visibility: hidden !important; }';
  document.head.appendChild(s); });"""


def shot(page: Page, name: str, lang: str, theme: str, full: bool = True) -> None:
    page.wait_for_timeout(500)
    page.screenshot(path=OUT / f"{name}-{lang}-{theme}.jpg", type="jpeg", quality=82, full_page=full)
    print("saved", name, lang, theme)


def prefs(page: Page, lang: str, theme: str, signed_out: bool = False) -> None:
    page.evaluate("([l, t, out]) => { localStorage.setItem('id-lang', l); localStorage.setItem('id-theme', t); if (out) localStorage.removeItem('id-token'); }",
                  [lang, theme, signed_out])
    page.goto(BASE)


def api(page: Page, method: str, path: str, body=None):
    return page.evaluate("""async ([m, p, b]) => {
        const r = await fetch('/api' + p, { method: m, headers: { 'Content-Type': 'application/json',
            Authorization: 'Bearer ' + localStorage.getItem('id-token') }, body: b === null ? undefined : JSON.stringify(b) });
        return await r.json().catch(() => null);
    }""", [method, path, body])


def go(page: Page, hash_: str) -> None:
    page.evaluate(f"location.hash = '#/{hash_}'")
    page.wait_for_timeout(900)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1360, "height": 860}, device_scale_factor=1)
    ctx.add_init_script(STEADY)
    page = ctx.new_page()
    page.goto(BASE)
    for lang, theme in COMBOS:
        prefs(page, lang, theme, signed_out=True)
        page.wait_for_selector(".roles")
        shot(page, "00-sign-in", lang, theme)
    page.locator(".roles button").first.click()
    page.wait_for_selector(".nav")
    api(page, "POST", "/admin/reset", {})
    for lang, theme in COMBOS:
        prefs(page, lang, theme)
        page.wait_for_selector(".welcome")
        shot(page, "01-welcome", lang, theme)
    api(page, "POST", "/samples/demo", {})
    # Polled from here: wait_for_function treats the promise an async predicate returns as true and would not wait.
    for _ in range(240):  # the sample history is read one invoice at a time
        s = api(page, "GET", "/stats", None)
        if s["total"] > 0 and s["by_status"]["queued"] + s["by_status"]["processing"] == 0:
            break
        page.wait_for_timeout(500)
    job = api(page, "POST", "/evaluation/run", {"mode": "rules"})["job"]
    for _ in range(240):
        if api(page, "GET", f"/evaluation/jobs/{job}", None)["status"] != "running":
            break
        page.wait_for_timeout(500)
    for lang, theme in COMBOS:
        prefs(page, lang, theme)
        page.wait_for_selector(".nav")
        go(page, "dashboard"); page.wait_for_selector(".oc-plot"); page.wait_for_timeout(500); shot(page, "02-dashboard", lang, theme)
        go(page, "intake"); shot(page, "03-intake", lang, theme)
        go(page, "runs"); page.wait_for_selector("tbody tr"); shot(page, "04-runs", lang, theme)
        page.locator("tbody tr", has=page.locator(".s-needs_review")).first.click()
        page.wait_for_selector(".modal .checks")
        shot(page, "05-run-detail", lang, theme, full=False)
        page.keyboard.press("Escape")
        go(page, "review"); page.wait_for_selector(".rq-item"); page.wait_for_selector(".checks"); shot(page, "06-review", lang, theme, full=False)
        go(page, "rules"); page.wait_for_selector(".rulecard"); shot(page, "07-rules", lang, theme)
        page.locator(".rulecard button.btn.small").last.click()
        page.wait_for_selector(".modal")
        shot(page, "08-rule-editor", lang, theme, full=False)
        page.keyboard.press("Escape")
        go(page, "vendors"); page.wait_for_selector("tbody tr"); shot(page, "09-vendors", lang, theme)
        go(page, "evaluation"); page.wait_for_timeout(600); shot(page, "10-evaluation", lang, theme)
        go(page, "audit"); page.wait_for_selector("tbody tr"); shot(page, "11-audit", lang, theme)
        go(page, "settings"); shot(page, "12-settings", lang, theme)
    browser.close()
