"""Shared helpers for tests that drive the factory-built stack or read pages."""

import json
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import NamedTuple

from fastapi import FastAPI

from app.middleware import (
    BodySizeLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)

DOCKERFILE = Path(__file__).parent.parent / ".devcontainer" / "Dockerfile"


def distribution_entrypoint() -> list[str]:
    """
    Return the distribution image's ENTRYPOINT, as the argv Docker would run.

    Exec-form ENTRYPOINT is a JSON array, so parsing it (rather than reading
    the line as text) yields the arguments with their backslash-escaped quotes
    resolved - the very list a test can hand to subprocess to run the image's
    command outside the image, which is the only way to exercise it in a dev
    container that has no Docker.
    """
    line = next(
        (
            line
            for line in DOCKERFILE.read_text().splitlines()
            if line.startswith("ENTRYPOINT ")
        ),
        "",
    )
    assert line, "the distribution stage has no ENTRYPOINT"
    argv: list[str] = json.loads(line.removeprefix("ENTRYPOINT "))
    return argv


def distribution_environment() -> dict[str, str]:
    """
    Return the run-time defaults the distribution stage declares with ENV.

    Only the stage's own `ENV NAME=value` lines, so a test running the
    entrypoint above starts from exactly the environment the image ships -
    a default that changes in the Dockerfile changes what the test asserts on,
    instead of drifting away from a copy hard-coded here.
    """
    _, marker, distribution = DOCKERFILE.read_text().partition(
        "FROM base AS distribution"
    )
    assert marker, "the distribution stage was renamed"
    return {
        match["name"]: match["value"].strip('"')
        for match in re.finditer(
            r"^ENV (?P<name>\w+)=(?P<value>.*)$", distribution, re.MULTILINE
        )
    }


def security_headers_app(application: RequestIDMiddleware) -> SecurityHeadersMiddleware:
    """Return the header stamp after asserting correlation wraps it."""
    assert isinstance(application, RequestIDMiddleware)
    assert isinstance(application.app, SecurityHeadersMiddleware)
    return application.app


def body_limited_app(application: RequestIDMiddleware) -> BodySizeLimitMiddleware:
    """Return the body guard after asserting the two wrappers above it."""
    inner = security_headers_app(application).app
    assert isinstance(inner, BodySizeLimitMiddleware)
    return inner


def framework_app(application: RequestIDMiddleware) -> FastAPI:
    """
    Return the FastAPI instance after asserting the production wrapper order.

    The isinstance chain is itself a test: correlation outermost, header stamp
    inside it, then the body guard, framework innermost (see "Composition
    root" in docs/ARCHITECTURE.md). Every in-process test unwraps through
    here, so a reordered stack fails loudly everywhere at once.
    """
    inner = body_limited_app(application).app
    assert isinstance(inner, FastAPI)
    return inner


class EmittedUrl(NamedTuple):
    """One URL a page emits, with the tag and ``rel`` that carry it."""

    tag: str
    rel: str
    url: str

    @property
    def is_canonical(self) -> bool:
        """Whether this is the canonical link, the page's one absolute URL."""
        return self.tag == "link" and self.rel == "canonical"

    @property
    def origin(self) -> tuple[str, str]:
        """The (scheme, host:port) this URL names, or ("", "") if it names none."""
        parts = urllib.parse.urlsplit(self.url)
        return parts.scheme, parts.netloc

    @property
    def names_an_origin(self) -> bool:
        """
        Whether this URL points at an origin rather than resolving against the page's.

        Parsed, not tested for the substring "://": that misses a
        scheme-relative "//example.com/css/style.css", which names a host
        just as much and leaves the deployment just as far behind. A
        root-relative URL carries neither a scheme nor a netloc, so any of
        either is an origin the app had to reconstruct for itself.
        """
        return any(self.origin)


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
