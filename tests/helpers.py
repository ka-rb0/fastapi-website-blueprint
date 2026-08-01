"""Shared helpers for tests that drive the factory-built stack or read pages."""

from html.parser import HTMLParser
from typing import NamedTuple

from fastapi import FastAPI

from app.middleware import BodySizeLimitMiddleware, SecurityHeadersMiddleware


def framework_app(application: SecurityHeadersMiddleware) -> FastAPI:
    """
    Return the FastAPI instance after asserting the production wrapper order.

    The isinstance chain is itself a test: header stamp outermost, body guard
    inside it, framework innermost (see "Composition root" in
    docs/ARCHITECTURE.md). Every in-process test unwraps through here, so a
    reordered stack fails loudly everywhere at once.
    """
    assert isinstance(application, SecurityHeadersMiddleware)
    assert isinstance(application.app, BodySizeLimitMiddleware)
    assert isinstance(application.app.app, FastAPI)
    return application.app.app


class EmittedUrl(NamedTuple):
    """One URL a page emits, with the tag and ``rel`` that carry it."""

    tag: str
    rel: str
    url: str

    @property
    def is_canonical(self) -> bool:
        """Whether this is the canonical link, the page's one absolute URL."""
        return self.tag == "link" and self.rel == "canonical"


class _UrlCollector(HTMLParser):
    """Collect every URL-bearing attribute value (href/src/action) of a page."""

    _URL_ATTRIBUTES = frozenset({"action", "href", "src"})

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[EmittedUrl] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        rel = values.get("rel") or ""
        self.urls += [
            EmittedUrl(tag=tag, rel=rel, url=value)
            for name, value in attrs
            if name in self._URL_ATTRIBUTES and value is not None
        ]


def emitted_urls(html: str) -> list[EmittedUrl]:
    """
    Return every URL the page emits, tagged with what carries it.

    Parsed rather than pattern-matched, because the two kinds of URL this
    project emits are told apart by their element, not their text: the
    canonical link is absolute on purpose, everything the browser fetches to
    render the page is root-relative (see "URL generation" in
    docs/ARCHITECTURE.md).
    """
    collector = _UrlCollector()
    collector.feed(html)
    return collector.urls
