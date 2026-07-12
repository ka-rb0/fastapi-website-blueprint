"""
Guards for the hand-mirrored hex values in the static frontend.

css/theme.css is the source of truth for the design tokens, but two files
can't read CSS variables and mirror hex values by hand: the
<meta name="theme-color"> tags in index.html (--bg) and favicon.svg
(--accent). These tests turn those files' "keep in sync" comments into an
enforced invariant. Pure file checks - no server needed.
"""

import re
from pathlib import Path

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
