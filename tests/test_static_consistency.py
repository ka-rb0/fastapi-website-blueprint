"""
Guards for the hand-mirrored values in the static frontend.

The static files can't read their sources of truth and mirror values by
hand: the <meta name="theme-color"> tags in index.html and favicon.svg
mirror design tokens from css/theme.css (--bg and --accent), and the shout
input's maxlength mirrors MAX_SHOUT_LENGTH from app.main. These tests turn
those files' "keep in sync" comments into an enforced invariant. Pure file
checks - no server needed.
"""

import re
from pathlib import Path

from app.main import MAX_SHOUT_LENGTH

STATIC_DIR = Path(__file__).parent.parent / "src" / "app" / "static"

HEX = r"#[0-9a-fA-F]{6}"


def _token(name: str) -> tuple[str, str]:
    """Return the (light, dark) hex pair of a token in css/theme.css."""
    css = (STATIC_DIR / "css" / "theme.css").read_text()
    match = re.search(rf"--{name}:\s*light-dark\(({HEX}),\s*({HEX})\)", css)
    assert match, f"--{name}: light-dark(...) not found in theme.css"
    return match.group(1), match.group(2)


def test_theme_color_metas_match_bg() -> None:
    """The <meta name="theme-color"> tags mirror --bg for each scheme."""
    light, dark = _token("bg")
    html = (STATIC_DIR / "index.html").read_text()
    metas = dict(
        re.findall(
            rf'media="\(prefers-color-scheme: (light|dark)\)"\s+content="({HEX})"',
            html,
        )
    )
    assert metas == {"light": light, "dark": dark}


def test_favicon_uses_light_accent() -> None:
    """The favicon's fixed color is the light-scheme --accent."""
    light_accent, _ = _token("accent")
    svg = (STATIC_DIR / "favicon.svg").read_text()
    colors = set(re.findall(HEX, svg))
    assert colors == {light_accent}


def test_shout_input_maxlength_matches_api_limit() -> None:
    """The shout input's maxlength mirrors MAX_SHOUT_LENGTH in app.main."""
    html = (STATIC_DIR / "index.html").read_text()
    match = re.search(r'<input\b[^>]*\bid="shout-input"[^>]*>', html, re.DOTALL)
    assert match, '<input id="shout-input" ...> not found in index.html'
    maxlength = re.search(r'\bmaxlength="(\d+)"', match.group(0))
    assert maxlength, "the shout input carries no maxlength attribute"
    assert int(maxlength.group(1)) == MAX_SHOUT_LENGTH
