"""
The two log renderings: readable for a human, JSON for a log pipeline.

`LOG_FORMAT` picks one, and picking is all it does - both renderings carry the
same fields, correlation ID included, which is what makes the choice a
deployment's rather than a code change (see "Request correlation" in
docs/ARCHITECTURE.md). The text rendering is pinned by
tests/test_request_id.py, which reads real log lines; this covers the JSON one
in the same two halves - the object a record turns into, and the stream a
server actually writes, because a formatter uvicorn's own loggers bypassed
would pass the first half while shipping half a log in plain text.
"""

import json
import logging
import os
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from app.observability import (
    NO_REQUEST_ID,
    REQUEST_ID_HEADER,
    CorrelationFilter,
    JsonLogFormatter,
    LogFormat,
    bind_request_id,
)
from app.routers.probes import LIVENESS_PATH

from .conftest import next_test_port, run_server
from .helpers import distribution_environment

# The keys a consumer of these logs writes its queries against, spelled out
# rather than read back from JSON_LOG_FIELDS: asserting against the mapping the
# formatter itself reads would pass no matter what the mapping said. Every
# record carries these; `trace_id`/`span_id` join them only while a span is
# current, which tests/test_telemetry.py covers.
JSON_KEYS = {"time", "level", "logger", "request_id", "message"}


def _record(**overrides: object) -> logging.LogRecord:
    """Build a record the way logging does, with `overrides` applied to it."""
    record = logging.LogRecord(
        name="app.demo",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        # A %-style message with its argument still separate, as every logging
        # call in this app makes one: the formatter has to interpolate it, and
        # a JSON object holding "shouted %s" is the bug that would say so.
        msg="shouted %s",
        args=("twice",),
        exc_info=None,
    )
    record.__dict__.update(overrides)
    return record


def test_a_record_becomes_one_json_object_with_the_declared_fields() -> None:
    """
    One record, one line, exactly the keys a consumer is promised.

    The line matters as much as the keys: a log pipeline splits a container's
    stdout on newlines, so a rendering that emitted two would be two events,
    one of them unparsable.
    """
    record = _record()
    with bind_request_id("traced-id"):
        CorrelationFilter().filter(record)
    line = JsonLogFormatter().format(record)

    assert "\n" not in line, "a multi-line record is more than one log event"
    payload = json.loads(line)
    assert set(payload) == JSON_KEYS
    assert payload["level"] == "WARNING"
    assert payload["logger"] == "app.demo"
    assert payload["request_id"] == "traced-id"
    assert payload["message"] == "shouted twice", "the %-argument was not applied"


def test_the_timestamp_is_rfc_3339_in_utc() -> None:
    """
    Parseable as an instant, and the same instant everywhere.

    The base class's default is local time with a comma before the
    milliseconds - not a timestamp any aggregator parses, and not one that
    orders records against a replica in another zone.
    """
    payload = json.loads(JsonLogFormatter().format(_record()))

    moment = datetime.fromisoformat(payload["time"])
    assert moment.tzinfo == UTC
    assert payload["time"].endswith("Z")


def test_a_field_the_record_never_got_is_left_out_rather_than_raising() -> None:
    """
    A record that missed CorrelationFilter still logs, minus that one key.

    `request_id` is the field nothing but the filter supplies, so any handler
    installed without it - a library's, a test harness's - hands this formatter
    a record that has no such attribute. Reaching for it anyway would raise
    inside the handler, where logging swallows the record and leaves
    "--- Logging error ---" where the log line should have been.
    """
    payload = json.loads(JsonLogFormatter().format(_record()))

    assert "request_id" not in payload
    assert payload["message"] == "shouted twice", "the rest of the record survived"


def test_a_traceback_reaches_the_pipeline_with_the_record_it_belongs_to() -> None:
    """
    An exception record carries the traceback, escaped into the same line.

    This is the record the correlation ID exists for: uvicorn logs the
    traceback for a failed request through the handler configured here. A
    rendering that dropped `exc_info` - it is a field of the record, not of the
    message - would ship "Exception in ASGI application" with the cause gone.
    """
    try:
        raise RuntimeError("kaboom")
    except RuntimeError as error:
        record = _record(exc_info=(type(error), error, error.__traceback__))
    line = JsonLogFormatter().format(record)

    assert "\n" not in line, "the traceback's newlines must stay inside the string"
    assert "RuntimeError: kaboom" in json.loads(line)["exception"]


def test_a_requested_stack_is_carried_the_same_way() -> None:
    """`stack_info=True` at a call site reaches the pipeline as its own field."""
    record = _record(stack_info="Stack (most recent call last):\n  somewhere")

    payload = json.loads(JsonLogFormatter().format(record))

    assert payload["stack"].startswith("Stack (most recent call last):")


def test_the_distribution_image_ships_the_json_rendering() -> None:
    """The image's environment is where production gets JSON, not a code edit."""
    assert distribution_environment().get("LOG_FORMAT") == LogFormat.JSON, (
        "the image no longer selects the JSON rendering, so a deployment's log"
        " aggregator receives lines meant for a human to read"
    )


def test_a_server_set_to_json_writes_nothing_but_json(tmp_path: Path) -> None:
    """
    Every line a real server emits is one JSON object, uvicorn's included.

    The whole stream, not a sampled line: uvicorn installs loggers of its own
    and `configure_logging` adopts them (see "Request correlation" in
    docs/ARCHITECTURE.md), so a regression there does not silence the access
    line - it leaves it in plain text in the middle of a JSON stream, where
    the aggregator drops it and nobody notices. The two lines asserted by name
    are the halves that would break independently: the access line comes from
    uvicorn's logger and carries the request's ID, the startup line comes from
    the app's own and belongs to no request.
    """
    log_path = tmp_path / "server.log"
    with (
        log_path.open("wb") as sink,
        run_server(
            next_test_port(), {**os.environ, "LOG_FORMAT": "json"}, output=sink
        ) as base,
    ):
        urllib.request.urlopen(
            urllib.request.Request(
                f"{base}{LIVENESS_PATH}", headers={REQUEST_ID_HEADER: "traced-id"}
            ),
            timeout=5,
        ).close()

    records = []
    for line in log_path.read_text().splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            raise AssertionError(f"a line bypassed the formatter: {line!r}") from None

    assert any(
        record["logger"] == "uvicorn.access"
        and record["request_id"] == "traced-id"
        and f"GET {LIVENESS_PATH}" in record["message"]
        for record in records
    ), f"no JSON access line correlated to the request:\n{records}"
    assert any(
        record["logger"] == "app.lifecycle"
        and record["request_id"] == NO_REQUEST_ID
        and "Serving static files" in record["message"]
        for record in records
    ), f"the startup line is not JSON, or borrowed an ID:\n{records}"
