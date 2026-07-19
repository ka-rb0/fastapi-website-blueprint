"""
Guards for the values the rendered pages derive from their sources of truth.

The templates no longer mirror anything by hand: the <meta name="theme-color">
tags get --bg from css/theme.css and the shout input's minlength/maxlength get
MIN/MAX_SHOUT_LENGTH from app.main, all injected as Jinja globals (see
src/app/main.py). These tests render the templates and check the injected
values against the sources, so a broken pipeline (dropped meta tag, hardcoded
value, reworded CSS the parser misses) fails loudly. favicon.svg is the one
file that still mirrors a token by hand - SVG isn't templated. Pure
file/render checks - no server needed.
"""

import re
from pathlib import Path

import pytest

from app.main import MAX_SHOUT_LENGTH, MIN_SHOUT_LENGTH, templates, theme_css_pair

STATIC_DIR = Path(__file__).parent.parent / "src" / "app" / "static"

HEX = r"#[0-9a-fA-F]{6}"


def _token(name: str) -> tuple[str, str]:
    """
    Return the (light, dark) hex pair of a token in css/theme.css.

    Deliberately its own parse rather than calling app.main's theme_css_pair:
    comparing the app's values against the app's own parser would be circular.
    """
    css = (STATIC_DIR / "css" / "theme.css").read_text()
    match = re.search(rf"--{name}:\s*light-dark\(({HEX}),\s*({HEX})\)", css)
    assert match, f"--{name}: light-dark(...) not found in theme.css"
    return match.group(1), match.group(2)


def _render(template: str) -> str:
    """Render a page template exactly as the routes do (same env, same globals)."""
    return templates.env.get_template(template).render()


@pytest.mark.parametrize("page", ["index.html", "not-found.html"])
def test_theme_color_metas_match_bg(page: str) -> None:
    """The rendered <meta name="theme-color"> tags carry --bg for each scheme."""
    light, dark = _token("bg")
    html = _render(page)
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


@pytest.mark.parametrize(
    ("attribute", "limit"),
    [("minlength", MIN_SHOUT_LENGTH), ("maxlength", MAX_SHOUT_LENGTH)],
)
def test_shout_input_length_limits_match_api(attribute: str, limit: int) -> None:
    """The rendered shout input mirrors MIN/MAX_SHOUT_LENGTH as its length limits."""
    html = _render("index.html")
    match = re.search(r'<input\b[^>]*\bid="shout-input"[^>]*>', html, re.DOTALL)
    assert match, '<input id="shout-input" ...> not found in the rendered index.html'
    value = re.search(rf'\b{attribute}="(\d+)"', match.group(0))
    assert value, f"the shout input carries no {attribute} attribute"
    assert int(value.group(1)) == limit


def test_theme_css_pair_rejects_missing_token() -> None:
    """A token the parser can't find fails loudly instead of rendering blanks."""
    with pytest.raises(RuntimeError, match="no-such-token"):
        theme_css_pair("no-such-token")
