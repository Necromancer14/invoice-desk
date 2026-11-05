"""Browser walk-through against a running server: python tools/e2e.py [base_url]. Fails loudly if a screen breaks. Saves screenshots to docs/screens."""
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screens"
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_page(viewport={"width": 1360, "height": 860}, device_scale_factor=1)
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.goto(BASE)
    page.get_by_role("button", name="Admin").click()
    expect(page.get_by_role("heading", name="Dashboard")).to_be_visible()
    page.screenshot(path=OUT / "01-empty-dashboard.png")

    page.get_by_role("button", name="Upload invoices").first.click()
    page.get_by_role("button", name="Load all 60").click()
    expect(page.get_by_role("heading", name="Runs")).to_be_visible()
    page.wait_for_function("document.querySelectorAll('tbody tr').length >= 30", timeout=20000)
    page.wait_for_timeout(2500)
    page.screenshot(path=OUT / "02-runs.png")

    page.get_by_role("button", name="Dashboard").click()
    expect(page.get_by_text("cleared without a person")).to_be_visible()
    page.screenshot(path=OUT / "03-dashboard.png")

    page.get_by_role("button", name="Review queue").first.click()
    expect(page.get_by_role("heading", name="Review queue")).to_be_visible()
    page.wait_for_selector("text=Why this needs a person")
    page.screenshot(path=OUT / "04-review.png")
    page.get_by_role("button", name="Approve").first.click()
    page.wait_for_timeout(800)

    page.get_by_role("button", name="Rules").first.click()
    page.get_by_role("button", name="Add rule").click()
    page.get_by_label("Name").fill("Flag invoices over 20,000")
    page.get_by_label("What it checks").select_option("amount_limit")
    page.get_by_label("max").fill("20000")
    page.get_by_role("button", name="Check impact on past invoices").click()
    page.wait_for_selector("text=past invoices")
    page.screenshot(path=OUT / "05-rule-editor.png")
    page.get_by_role("button", name="Save rule").click()
    expect(page.locator("b", has_text="Flag invoices over 20,000")).to_be_visible()
    page.screenshot(path=OUT / "06-rules.png")

    page.get_by_role("button", name="Evaluation").first.click()
    page.get_by_role("button", name="Run with built-in rules").click()
    page.wait_for_selector("text=same decision as the answer key", timeout=30000)
    page.screenshot(path=OUT / "07-evaluation.png", full_page=True)

    page.get_by_role("button", name="Audit log").first.click()
    page.wait_for_selector("text=rule.create")
    page.get_by_role("button", name="Settings").first.click()
    page.get_by_role("button", name="Google Gemini").click()
    page.wait_for_selector("text=Save and test connection")
    page.screenshot(path=OUT / "12-settings-ai.png", full_page=True)
    page.get_by_role("button", name="Switch theme").click()
    page.get_by_role("button", name="Dashboard").click()
    page.wait_for_timeout(400)
    page.screenshot(path=OUT / "08-dashboard-dark.png")
    page.get_by_role("button", name="Review queue").first.click()
    page.wait_for_timeout(800)
    page.screenshot(path=OUT / "09-review-dark.png")
    page.get_by_role("button", name="Switch language").click()
    page.wait_for_timeout(400)
    assert page.evaluate("document.documentElement.dir") == "rtl"
    page.screenshot(path=OUT / "10-arabic-rtl.png")

    # Arabic in the light theme: the screens people look at most. Labels are Arabic now, so navigate by URL
    # and wait for an Arabic heading plus a line that only shows once the page has its data.
    page.get_by_role("button", name="تغيير المظهر").click()  # "Switch theme"
    for shot, tab, heading, ready in [
        ("13-dashboard-ar", "dashboard", "لوحة المتابعة", "أُنجزت دون تدخل بشري"),
        ("14-review-ar", "review", "قائمة المراجعة", "سبب الحاجة إلى مراجعة بشرية"),
        ("15-rules-ar", "rules", "القواعد", "سجل الإصدارات"),
    ]:
        page.evaluate(f"location.hash = '#/{tab}'")
        expect(page.get_by_role("heading", name=heading, exact=True)).to_be_visible()
        page.wait_for_selector(f"text={ready}")
        page.wait_for_timeout(500)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"{tab} scrolls sideways in Arabic"
        page.screenshot(path=OUT / f"{shot}.png")

    m = b.new_page(viewport={"width": 390, "height": 800}, device_scale_factor=2)
    m.goto(BASE)
    m.get_by_role("button", name="Reviewer").click()
    m.wait_for_timeout(600)
    m.screenshot(path=OUT / "11-mobile.png")
    b.close()
    if errors:
        print("BROWSER ERRORS:", *errors, sep="\n  ")
        sys.exit(1)
print("e2e ok")
