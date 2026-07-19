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
from tests.accessibility import (
    NON_TEXT_CONTRAST_MINIMUM,
    TEXT_CONTRAST_MINIMUM,
    contrast_ratio,
    hex_to_rgb,
)

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


def test_contrast_calculation_matches_wcag_reference_values() -> None:
    """Guard the calculator behind every contrast threshold assertion."""
    assert contrast_ratio((0, 0, 0), (255, 255, 255)) == pytest.approx(21)
    assert contrast_ratio((255, 255, 255), (255, 255, 255)) == pytest.approx(1)


@pytest.mark.parametrize(
    ("foreground", "background"),
    [
        ("fg", "bg"),
        ("fg", "surface"),
        ("muted", "bg"),
        ("muted", "surface"),
        ("accent", "bg"),
        ("accent-fg", "accent"),
    ],
)
def test_text_token_pairs_meet_wcag_aa(foreground: str, background: str) -> None:
    """Every text/background pairing meets WCAG AA's 4.5:1 minimum."""
    foreground_colors = _token(foreground)
    background_colors = _token(background)
    for scheme, foreground_color, background_color in zip(
        ("light", "dark"), foreground_colors, background_colors, strict=True
    ):
        ratio = contrast_ratio(
            hex_to_rgb(foreground_color), hex_to_rgb(background_color)
        )
        assert ratio >= TEXT_CONTRAST_MINIMUM, (
            f"{scheme} {foreground} on {background} is {ratio:.3f}:1; "
            f"expected at least {TEXT_CONTRAST_MINIMUM}:1"
        )


@pytest.mark.parametrize(
    ("indicator", "adjacent"),
    [
        ("border", "bg"),
        ("border", "surface"),
        ("accent", "surface"),
        ("accent-fg", "accent"),
    ],
)
def test_ui_token_pairs_meet_wcag_aa(indicator: str, adjacent: str) -> None:
    """Control boundaries, selection states and focus rings meet 3:1."""
    indicator_colors = _token(indicator)
    adjacent_colors = _token(adjacent)
    for scheme, indicator_color, adjacent_color in zip(
        ("light", "dark"), indicator_colors, adjacent_colors, strict=True
    ):
        ratio = contrast_ratio(hex_to_rgb(indicator_color), hex_to_rgb(adjacent_color))
        assert ratio >= NON_TEXT_CONTRAST_MINIMUM, (
            f"{scheme} {indicator} against {adjacent} is {ratio:.3f}:1; "
            f"expected at least {NON_TEXT_CONTRAST_MINIMUM}:1"
        )


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
