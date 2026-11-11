"""Accessibility check: axe-core over the main pages, in English and Arabic, light and dark, plus keyboard checks.

    py tools/a11y_check.py [base_url]     (needs `npm ci` in web/ for axe-core, and a running server)

axe-core finds what can be found automatically (missing names, contrast, ARIA misuse, duplicate ids, landmarks).
It cannot judge whether the experience makes sense; that still needs a person with a keyboard and a screen reader.
Exits non-zero if axe reports a serious or critical problem or a keyboard check fails.
"""
import sys
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
AXE = (Path(__file__).resolve().parent.parent / "web" / "node_modules" / "axe-core" / "axe.min.js").read_text(encoding="utf-8")
PAGES = ["dashboard", "intake", "runs", "review", "rules", "vendors", "evaluation", "audit", "settings"]
problems: list[str] = []


def axe(page: Page, where: str) -> None:
    page.add_script_tag(content=AXE)
    result = page.evaluate("""async () => {
        const r = await axe.run(document, { runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'] } });
        return r.violations.map(v => ({ id: v.id, impact: v.impact, help: v.help, nodes: v.nodes.slice(0, 3).map(n => n.target.join(' ') + ' :: ' + (n.failureSummary || '').split('\\n')[1]) }));
    }""")
    for v in result:
        line = f"{where}: [{v['impact']}] {v['id']}: {v['help']}\n      " + "\n      ".join(v["nodes"])
        print(line)
        if v["impact"] in ("serious", "critical"):
            problems.append(f"{where}: {v['id']}")


def keyboard(page: Page) -> None:
    """Modals take focus and give it back; the review list and nav work from the keyboard."""
    page.evaluate("location.hash = '#/rules'")
    opener = page.get_by_role("button", name="Add rule")
    opener.focus()
    page.keyboard.press("Enter")
    expect(page.locator(".modal")).to_be_visible()
    inside = page.evaluate("!!document.activeElement.closest('.modal')")
    print(("ok   " if inside else "FAIL ") + "focus moves into the rule editor when it opens")
    if not inside:
        problems.append("keyboard: modal does not take focus")
    for _ in range(40):  # Tab must stay inside the open dialog
        page.keyboard.press("Tab")
        if not page.evaluate("!!document.activeElement.closest('.modal')"):
            print("FAIL Tab leaves the open rule editor")
            problems.append("keyboard: focus escapes the modal")
            break
    else:
        print("ok   Tab stays inside the open rule editor")
    page.keyboard.press("Escape")
    expect(page.locator(".modal")).to_have_count(0)
    back = page.evaluate("document.activeElement?.textContent?.trim()")
    print(("ok   " if back == "Add rule" else "FAIL ") + f"focus returns to the button that opened it ({back!r})")
    if back != "Add rule":
        problems.append("keyboard: focus not returned after closing the modal")
    page.evaluate("location.hash = '#/review'")
    page.wait_for_selector(".rq-item")
    roles = page.evaluate("[...document.querySelectorAll('.rq-items [role]')].map(e => e.getAttribute('role'))")
    ok = "option" not in roles
    print(("ok   " if ok else "FAIL ") + "review list does not claim listbox keyboard behaviour it lacks")
    if not ok:
        problems.append("keyboard: review list uses role=option without arrow keys")


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_page(viewport={"width": 1360, "height": 860})
    page.goto(BASE)
    for lang in ("en", "ar"):
        for theme in ("light", "dark"):
            page.evaluate(f"localStorage.removeItem('id-token'); localStorage.setItem('id-lang', '{lang}'); localStorage.setItem('id-theme', '{theme}')")
            page.goto(BASE)
            page.wait_for_selector(".roles")
            axe(page, f"sign-in {lang}/{theme}")
            page.locator(".roles button").first.click()
            page.wait_for_selector(".nav")
            # an empty database first: the welcome card and the reset dialog, then the samples for the other pages
            tok = page.evaluate("localStorage.getItem('id-token')")
            page.evaluate("""async (t) => fetch('/api/admin/reset', { method: 'POST', body: '{}',
                headers: { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' } })""", tok)
            page.evaluate("location.hash = '#/dashboard'; location.reload()")
            page.wait_for_selector(".welcome")
            axe(page, f"welcome card {lang}/{theme}")
            page.evaluate("location.hash = '#/settings'")
            page.locator(".btn.danger").first.click()
            page.wait_for_selector(".modal")
            axe(page, f"reset dialog {lang}/{theme}")
            page.keyboard.press("Escape")
            page.evaluate("""async (t) => { const h = { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' };
                await fetch('/api/samples/submit', { method: 'POST', headers: h, body: JSON.stringify({ files: ['inv-006.txt', 'inv-012.txt', 'inv-013.txt', 'inv-003.txt'] }) }); }""", tok)
            page.wait_for_timeout(1500)
            for name in PAGES:
                page.evaluate(f"location.hash = '#/{name}'")
                page.wait_for_timeout(700)
                axe(page, f"{name} {lang}/{theme}")
            page.evaluate("location.hash = '#/rules'")
            page.locator(".rulecard button.btn.small").last.click()
            page.wait_for_selector(".modal")
            axe(page, f"rule editor {lang}/{theme}")
            page.keyboard.press("Escape")
            page.evaluate("location.hash = '#/vendors'")
            page.locator(".page-head .btn.primary").first.click()
            page.wait_for_selector(".modal")
            axe(page, f"vendor editor {lang}/{theme}")
            page.keyboard.press("Escape")
            # an XML invoice laid out as an invoice, with its source XML opened
            page.evaluate("""async (t) => { const h = { Authorization: 'Bearer ' + t, 'Content-Type': 'application/json' };
                await fetch('/api/samples/submit', { method: 'POST', headers: h, body: JSON.stringify({ files: ['inv-084.xml'] }) }); }""", tok)
            page.wait_for_timeout(1000)
            page.evaluate("location.hash = '#/runs'")
            page.locator("tbody tr", has_text="inv-084.xml").first.click()
            page.wait_for_selector(".modal .inv")
            page.locator(".inv-src summary").click()
            page.wait_for_selector(".modal pre.xml")
            axe(page, f"XML invoice view {lang}/{theme}")
            page.keyboard.press("Escape")
            # the review copilot with a suggestion, its findings and its steps opened
            page.evaluate("location.hash = '#/review'")
            page.locator(".copilot .btn").first.click()
            page.wait_for_selector(".cp-rec")
            page.locator(".cp-steps summary").click()
            axe(page, f"review copilot {lang}/{theme}")
    page.evaluate("localStorage.setItem('id-lang', 'en'); localStorage.setItem('id-theme', 'light'); location.reload()")
    page.wait_for_selector(".nav")
    keyboard(page)
    browser.close()

if problems:
    print(f"\n{len(problems)} serious problem(s):", *sorted(set(problems)), sep="\n  ")
    sys.exit(1)
print("\nno serious or critical accessibility problems found by axe, keyboard checks passed")
