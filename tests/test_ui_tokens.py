"""The portal's design foundations: one token set, self-hosted fonts, tabular figures.

These read the source files only; the browser checks (tools/ui_check.py, tools/a11y_check.py) cover behaviour and contrast.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
CSS = (WEB / "src" / "styles.css").read_text(encoding="utf-8")
HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _token_blocks(css: str) -> tuple[str, str]:
    """(the :root token blocks, everything else)."""
    blocks = re.findall(r":root(?:\[data-theme=\"dark\"\])?\s*\{[^}]*\}", css)
    rest = css
    for b in blocks:
        rest = rest.replace(b, "")
    return "".join(blocks), rest


def test_colours_live_only_in_the_tokens():
    tokens, rest = _token_blocks(CSS)
    assert "--brand:" in tokens and "--bad:" in tokens and "--risk:" in tokens
    assert HEX.findall(rest) == [], "hard-coded colour outside the :root tokens"
    assert "rgba(" not in rest and "rgb(" not in rest


def test_light_and_dark_define_the_same_colour_tokens():
    light = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    dark = re.search(r":root\[data-theme=\"dark\"\]\s*\{([^}]*)\}", CSS).group(1)
    colour = lambda block: {m for m in re.findall(r"(--[\w-]+):\s*#", block)}  # noqa: E731
    assert colour(light) == colour(dark)


def test_components_use_no_hard_coded_colours():
    for f in (WEB / "src").rglob("*.tsx"):
        assert HEX.findall(f.read_text(encoding="utf-8")) == [], f"hard-coded colour in {f.name}"


def test_no_frosted_glass():
    assert "backdrop-filter" not in CSS
    assert "--glass" not in CSS


def test_fonts_are_self_hosted_plex():
    sources = re.findall(r"url\(\"([^\"]+)\"\)", CSS)
    assert sources and all(s.startswith("/fonts/") for s in sources)
    for s in sources:
        name = s.removeprefix("/fonts/")
        assert (WEB / "public" / "fonts" / name).is_file()
        assert (WEB / "dist" / "fonts" / name).is_file(), "rebuild web/dist"
    assert "IBM Plex Sans Arabic" in CSS and '"IBM Plex Sans"' in CSS
    assert (WEB / "public" / "fonts" / "IBM-Plex-OFL.txt").is_file()
    assert "http://" not in CSS and "https://" not in CSS
    assert "fonts.googleapis" not in (WEB / "index.html").read_text(encoding="utf-8")


def test_numbers_are_tabular_everywhere():
    body = re.search(r"\nbody\s*\{([^}]*)\}", CSS).group(1)
    assert "tabular-nums" in body


def test_status_colours_are_defined_once():
    # each status class maps to the shared tokens, nowhere else
    assert re.search(r"\.s-approved[^{]*\{[^}]*var\(--ok-bg\)[^}]*var\(--ok\)", CSS)
    assert re.search(r"\.s-needs_review[^{]*\{[^}]*var\(--warn-bg\)[^}]*var\(--warn\)", CSS)
    assert re.search(r"\.s-rejected[^{]*\{[^}]*var\(--bad-bg\)[^}]*var\(--bad\)", CSS)
    assert re.search(r"\.pill\.risk-pill\s*\{[^}]*var\(--risk\)", CSS)
