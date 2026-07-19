"""End-to-end tests in headless Chromium via Playwright."""

import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, ConsoleMessage, Page, expect, sync_playwright

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
def browser() -> Iterator[Browser]:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser: Browser, server: str) -> Iterator[Page]:
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


def test_shout_round_trip(page: Page) -> None:
    """The example form posts the text to /api/shout and renders the reply."""
    page.get_by_label("Text to shout").fill("hello")
    page.get_by_role("button", name="Shout").click()
    # <output> exposes the implicit ARIA role "status"
    expect(page.get_by_role("status")).to_have_text("HELLO")


@pytest.mark.online
def test_docs_renders_swagger_ui(browser: Browser, server: str) -> None:
    """
    The /docs page renders under its relaxed CSP (DOCS_CSP in app.main).

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


def test_follows_os_scheme_until_choice(browser: Browser, server: str) -> None:
    """Without a saved choice, Auto is checked and CSS follows the OS."""
    backgrounds = {}
    for scheme in ("light", "dark"):
        page = browser.new_page(color_scheme=scheme)
        try:
            page.goto(server)
            assert page.locator("html").get_attribute("data-theme") is None
            expect(page.get_by_role("radio", name="Auto")).to_be_checked()
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
    page.get_by_role("radio", name="Auto").focus()
    page.keyboard.press("ArrowRight")
    expect(page.get_by_role("radio", name="Dark")).to_be_checked()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_focus_ring_visible_on_checked_segment(page: Page) -> None:
    """
    Tabbing into the group must show a visible focus ring.

    Tab always enters a radio group at its *checked* radio, and that segment's
    background is the accent color - a ring in the accent color would vanish
    into it, making keyboard focus look like it skipped the group entirely.
    """
    page.keyboard.press("Tab")
    expect(page.get_by_role("radio", name="Auto")).to_be_focused()
    style = page.evaluate(
        "() => {"
        "  const label = document.querySelector("
        "    '.theme-switch label:has(input:checked)');"
        "  const s = getComputedStyle(label);"
        "  return {"
        "    outlineStyle: s.outlineStyle,"
        "    outlineColor: s.outlineColor,"
        "    background: s.backgroundColor,"
        "  };"
        "}"
    )
    assert style["outlineStyle"] == "solid", "no focus outline on the checked segment"
    assert style["outlineColor"] != style["background"], (
        "focus ring blends into the checked segment's background"
    )


def test_auto_restores_os_theme(page: Page) -> None:
    """Auto clears the saved choice and returns to following the OS."""
    page.get_by_role("radio", name="Dark").check()
    page.get_by_role("radio", name="Auto").check()
    # the auto-waiting expect first: once Auto reads checked, the same change
    # handler has also removed data-theme and cleared localStorage
    expect(page.get_by_role("radio", name="Auto")).to_be_checked()
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
