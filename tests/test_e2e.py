"""End-to-end tests in headless Chromium via Playwright."""

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, ConsoleMessage, Page, expect, sync_playwright


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


def test_docs_renders_swagger_ui(browser: Browser, server: str) -> None:
    """
    The /docs page renders under its relaxed CSP (DOCS_CSP in app.main).

    Rendering the schema proves the whole chain: the CDN assets and inline
    boot script are allowed through, and Swagger UI paints. CSP violations
    surface as console errors, so any that slip past the render checks are
    asserted away too. Needs cdn.jsdelivr.net reachable - just like the
    /docs page itself.
    """
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
    """Without a saved choice, Auto is pressed and CSS follows the OS."""
    backgrounds = {}
    for scheme in ("light", "dark"):
        page = browser.new_page(color_scheme=scheme)
        try:
            page.goto(server)
            assert page.locator("html").get_attribute("data-theme") is None
            expect(page.get_by_role("button", name="Auto")).to_have_attribute(
                "aria-pressed", "true"
            )
            backgrounds[scheme] = page.evaluate(
                "getComputedStyle(document.body).backgroundColor"
            )
        finally:
            page.close()
    assert backgrounds["light"] != backgrounds["dark"]


def test_theme_switch_toggles(page: Page) -> None:
    html = page.locator("html")
    page.get_by_role("button", name="Dark").click()
    expect(html).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("button", name="Dark")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_role("button", name="Light").click()
    expect(html).to_have_attribute("data-theme", "light")
    expect(page.get_by_role("button", name="Light")).to_have_attribute(
        "aria-pressed", "true"
    )


def test_auto_restores_os_theme(page: Page) -> None:
    """Auto clears the saved choice and returns to following the OS."""
    page.get_by_role("button", name="Dark").click()
    page.get_by_role("button", name="Auto").click()
    # the auto-waiting expect first: once Auto reads pressed, the same click
    # handler has also removed data-theme and cleared localStorage
    expect(page.get_by_role("button", name="Auto")).to_have_attribute(
        "aria-pressed", "true"
    )
    assert page.locator("html").get_attribute("data-theme") is None
    assert page.evaluate("localStorage.getItem('theme')") is None


def test_theme_persists_across_reload(page: Page) -> None:
    page.get_by_role("button", name="Dark").click()
    page.reload()
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_os_preference_not_persisted(page: Page) -> None:
    """Merely visiting must not write to localStorage - only clicking may."""
    assert page.evaluate("localStorage.getItem('theme')") is None
    page.get_by_role("button", name="Dark").click()
    assert page.evaluate("localStorage.getItem('theme')") == "dark"
