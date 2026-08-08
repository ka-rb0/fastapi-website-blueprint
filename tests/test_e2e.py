"""End-to-end tests in headless Chromium via Playwright."""

import urllib.error
import urllib.request
from collections.abc import Generator

import pytest
from playwright.sync_api import Browser, ConsoleMessage, Page, expect, sync_playwright

from tests.accessibility import NON_TEXT_CONTRAST_MINIMUM, contrast_ratio

CDN_URL = "https://cdn.jsdelivr.net"


def _cdn_reachable() -> bool:
    """Return True if the CDN answers at all - any HTTP status counts as reachable."""
    try:
        with urllib.request.urlopen(CDN_URL, timeout=5):
            return True
    except urllib.error.HTTPError as err:
        err.close()
        return True
    except OSError:
        return False


@pytest.fixture(scope="module")
def browser() -> Generator[Browser]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser, server: str) -> Generator[Page]:
    """Open a fresh page (own context, own localStorage) so tests stay independent."""
    page = browser.new_page()
    page.goto(server)
    yield page
    page.close()


def test_title(page: Page) -> None:
    expect(page).to_have_title("FastAPI Website Blueprint")


def test_heading_visible(page: Page) -> None:
    expect(
        page.get_by_role("heading", name="FastAPI Website Blueprint")
    ).to_be_visible()


def test_theme_switch_present(page: Page) -> None:
    expect(page.get_by_role("group", name="Color theme")).to_be_visible()


def test_user_input_controls_meet_wcag_2_2_label_requirements(page: Page) -> None:
    """
    Every data-entry control has a visible native label.

    WCAG 2.2 SC 3.3.2 (Labels or Instructions) requires labels or instructions
    whenever content requires user input. Native label association also makes
    each relationship programmatically determinable for SC 1.3.1.

    This checks every current and future text field, radio, checkbox, select,
    and textarea on the page. Hidden and button-like inputs do not accept data,
    so SC 3.3.2 does not apply to them.
    """
    controls = page.locator(
        "input:not([type=hidden]):not([type=button]):not([type=submit])"
        ":not([type=reset]):not([type=image]), select, textarea"
    )
    unlabeled_controls = controls.evaluate_all(
        """
        controls => controls.flatMap(control => {
          const visibleLabels = [...control.labels].filter(label => {
            const style = getComputedStyle(label);
            return label.textContent.trim()
              && label.getClientRects().length
              && style.visibility !== "hidden"
              && parseFloat(style.opacity) !== 0;
          });
          if (visibleLabels.length) {
            return [];
          }
          const id = control.id ? `#${control.id}` : "";
          const type = control instanceof HTMLInputElement
            ? `[type=${control.type}]`
            : "";
          return [`${control.tagName.toLowerCase()}${id}${type}`];
        })
        """
    )
    assert not unlabeled_controls, (
        "WCAG 2.2 SC 3.3.2 requires a visible label for every data-entry "
        f"control; missing native labels: {', '.join(unlabeled_controls)}"
    )


def test_shout_round_trip(page: Page) -> None:
    """The example form posts the text to /api/shout and renders the reply."""
    page.get_by_label("Text to shout").fill("hello")
    page.get_by_role("button", name="Shout").click()
    # <output> exposes the implicit ARIA role "status"
    expect(page.get_by_role("status")).to_have_text("HELLO")


@pytest.mark.online
def test_docs_renders_swagger_ui(browser: Browser, server: str) -> None:
    """
    The /docs page renders under its relaxed CSP (DOCS_CSP in app.middleware).

    Rendering the schema proves the whole chain: the CDN assets and inline
    boot script are allowed through, and Swagger UI paints. CSP violations
    surface as console errors, so any that slip past the render checks are
    asserted away too. Needs cdn.jsdelivr.net reachable - just like the
    /docs page itself - hence the `online` marker and the reachability
    probe below.
    """
    if not _cdn_reachable():
        pytest.skip(
            f"{CDN_URL} is unreachable - no internet connection? The /docs page "
            "loads Swagger UI from that CDN, so this test cannot run offline. "
            "Use `scripts/test --offline` (or `pytest -m 'not online'`) to "
            "deselect internet-dependent tests explicitly."
        )
    csp_errors: list[str] = []

    def on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error" and "Content Security Policy" in msg.text:
            csp_errors.append(msg.text)

    page = browser.new_page()
    try:
        page.on("console", on_console)
        page.goto(f"{server}/docs")
        ui = page.locator("#swagger-ui")
        expect(ui).to_contain_text("FastAPI Website Blueprint")
        expect(ui).to_contain_text("/api/shout")
        assert csp_errors == []
    finally:
        page.close()


def test_mobile_layout(browser: Browser, server: str) -> None:
    """
    At a narrow phone viewport nothing may overflow or overlap.

    The fixed theme switch and the wide letter-spaced heading are only
    exercised at Playwright's default desktop viewport by the other tests.
    """
    page = browser.new_page(viewport={"width": 375, "height": 667})
    try:
        page.goto(server)
        assert page.evaluate(
            "document.documentElement.scrollWidth"
            " <= document.documentElement.clientWidth"
        ), "page overflows horizontally at 375px"

        heading = page.get_by_role("heading", name="FastAPI Website Blueprint")
        switch = page.get_by_role("group", name="Color theme")
        expect(heading).to_be_visible()
        expect(switch).to_be_visible()
        heading_box = heading.bounding_box()
        switch_box = switch.bounding_box()
        assert heading_box is not None and switch_box is not None
        overlaps = (
            heading_box["x"] < switch_box["x"] + switch_box["width"]
            and switch_box["x"] < heading_box["x"] + heading_box["width"]
            and heading_box["y"] < switch_box["y"] + switch_box["height"]
            and switch_box["y"] < heading_box["y"] + heading_box["height"]
        )
        assert not overlaps, "theme switch overlaps the heading at 375px"
    finally:
        page.close()


def test_js_dependent_controls_hidden_without_javascript(
    browser: Browser, server: str
) -> None:
    """
    With JavaScript disabled, the page degrades to working static content.

    Both interactive examples only function through their modules - the
    theme radios have no effect without js/theme-switch.js, and a native
    submit of the shout form would send a form-encoded POST to the
    JSON-only endpoint, landing on a 422 error page. Each ships hidden and
    is revealed by its script, so a no-JS visitor sees no dead controls.
    """
    page = browser.new_page(java_script_enabled=False)
    try:
        page.goto(server)
        expect(
            page.get_by_role("heading", name="FastAPI Website Blueprint")
        ).to_be_visible()
        expect(page.locator(".theme-switch")).to_be_hidden()
        expect(page.locator("#shout-form")).to_be_hidden()
    finally:
        page.close()


def test_forced_colors_keeps_selection_visible(browser: Browser, server: str) -> None:
    """
    In forced-colors mode the checked segment stays distinguishable.

    The mode overrides the authored background/color pair that normally
    marks the selection, so style.css restates it under @media
    (forced-colors: active) with system colors - the one palette the mode
    preserves - plus an underline as a non-color indicator.
    """
    page = browser.new_page(forced_colors="active")
    try:
        page.goto(server)
        styles = page.evaluate(
            "() => {"
            "  const style = (selector) => {"
            "    const s = getComputedStyle(document.querySelector(selector));"
            "    return {"
            "      background: s.backgroundColor,"
            "      decoration: s.textDecorationLine,"
            "    };"
            "  };"
            "  return {"
            "    checked: style('.theme-switch label:has(input:checked)'),"
            "    unchecked: style('.theme-switch label:has(input:not(:checked))'),"
            "  };"
            "}"
        )
        assert styles["checked"]["background"] != styles["unchecked"]["background"], (
            "forced colors leave the checked segment's background "
            "indistinguishable from its neighbors"
        )
        assert styles["checked"]["decoration"] == "underline"
        assert styles["unchecked"]["decoration"] == "none"
    finally:
        page.close()


def test_follows_os_scheme_until_choice(browser: Browser, server: str) -> None:
    """Without a saved choice, System is checked and CSS follows the OS."""
    backgrounds = {}
    for scheme in ("light", "dark"):
        page = browser.new_page(color_scheme=scheme)
        try:
            page.goto(server)
            assert page.locator("html").get_attribute("data-theme") is None
            expect(page.get_by_role("radio", name="System")).to_be_checked()
            backgrounds[scheme] = page.evaluate(
                "getComputedStyle(document.body).backgroundColor"
            )
        finally:
            page.close()
    assert backgrounds["light"] != backgrounds["dark"]


def test_theme_switch_toggles(page: Page) -> None:
    html = page.locator("html")
    page.get_by_role("radio", name="Dark").check()
    expect(html).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("radio", name="Dark")).to_be_checked()
    page.get_by_role("radio", name="Light").check()
    expect(html).to_have_attribute("data-theme", "light")
    expect(page.get_by_role("radio", name="Light")).to_be_checked()


def test_keyboard_arrow_moves_selection(page: Page) -> None:
    """
    Arrow keys move the selection and apply the theme.

    The native radio behavior the group relies on instead of custom key
    handling (see base.html).
    """
    page.get_by_role("radio", name="System").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("radio", name="Dark")).to_be_checked()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_focus_ring_has_sufficient_contrast_on_checked_segment(
    page: Page, theme: str
) -> None:
    """
    Tabbing into the group must show a visible focus ring.

    Tab always enters a radio group at its *checked* radio, and that segment's
    background is the accent color - a ring in the accent color would vanish
    into it, making keyboard focus look like it skipped the group entirely.
    """
    radio = page.get_by_role("radio", name=theme)
    page.keyboard.press("Tab")
    page.keyboard.press("ArrowLeft" if theme == "Light" else "ArrowRight")
    expect(radio).to_be_focused()
    style = page.evaluate(
        "() => {"
        "  const label = document.querySelector("
        "    '.theme-switch label:has(input:checked)');"
        "  const s = getComputedStyle(label);"
        "  return {"
        "    outlineStyle: s.outlineStyle,"
        "    outlineColor: [...s.outlineColor.matchAll(/\\d+/g)].map(Number),"
        "    background: [...s.backgroundColor.matchAll(/\\d+/g)].map(Number),"
        "  };"
        "}"
    )
    assert style["outlineStyle"] == "solid", "no focus outline on the checked segment"
    ratio = contrast_ratio(style["outlineColor"], style["background"])
    assert ratio >= NON_TEXT_CONTRAST_MINIMUM, (
        f"{theme.lower()} focus ring contrast is {ratio:.3f}:1; expected at least "
        f"{NON_TEXT_CONTRAST_MINIMUM}:1"
    )


def test_auto_restores_os_theme(page: Page) -> None:
    """System clears the saved choice and returns to following the OS."""
    page.get_by_role("radio", name="Dark").check()
    page.get_by_role("radio", name="System").check()
    # the auto-waiting expect first: once System reads checked, the same change
    # handler has also removed data-theme and cleared localStorage
    expect(page.get_by_role("radio", name="System")).to_be_checked()
    assert page.locator("html").get_attribute("data-theme") is None
    assert page.evaluate("localStorage.getItem('theme')") is None


def test_theme_persists_across_reload(page: Page) -> None:
    page.get_by_role("radio", name="Dark").check()
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_os_preference_not_persisted(page: Page) -> None:
    """Merely visiting must not write to localStorage - only choosing may."""
    assert page.evaluate("localStorage.getItem('theme')") is None
    page.get_by_role("radio", name="Dark").check()
    assert page.evaluate("localStorage.getItem('theme')") == "dark"
