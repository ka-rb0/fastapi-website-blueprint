"""Request correlation: one ID per request, on every response and log record."""

import logging
import logging.config
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

REQUEST_ID_HEADER = "X-Request-ID"

# What %(request_id)s shows for records emitted outside a request - startup,
# shutdown, background work. A placeholder rather than an empty field, so
# every line keeps the same shape for whatever splits it into columns.
NO_REQUEST_ID = "-"

# An inbound ID is accepted as-is when it is 1-64 visible ASCII characters.
# That is the whole validation, because a correlation ID is an opaque token
# with no meaning to this app - only its shape can be wrong. The bound keeps
# an unbounded header out of every log line, and excluding space, CR, LF and
# the control characters is what makes echoing a client-supplied value safe:
# it can neither split the response header nor forge a line in the log. Sixty
# four characters admits every format an upstream is likely to send (a UUID, a
# 32-character hex string, a 55-character W3C `traceparent`).
_ACCEPTED_REQUEST_ID = re.compile(r"[\x21-\x7e]{1,64}")

# Human-readable rather than JSON: this is what a developer tails locally, and
# a blueprint should not presume a log pipeline. Swapping in a JSON formatter
# is a change to this one string plus the formatter class below it - the ID
# reaches the record either way, because the filter puts it there.
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"

_request_id: ContextVar[str] = ContextVar("request_id", default=NO_REQUEST_ID)


def get_request_id() -> str:
    """Return the current request's correlation ID, or ``-`` outside a request."""
    return _request_id.get()


@contextmanager
def bind_request_id(candidate: str | None) -> Iterator[str]:
    """
    Bind a correlation ID for the duration of the block and yield it.

    ``candidate`` is the inbound header value, if any: a usable one is kept so
    a trace spans every service that handled the request, anything else
    (missing, malformed, absurdly long) is replaced by a fresh ID rather than
    rejected - correlation is a diagnostic, never a reason to fail a request.

    A context variable, not a request attribute, so code that never sees the
    request - a logger deep in a call stack, a helper module - still emits the
    ID. On a clean exit it is reset on the way out: each ASGI request runs in
    its own task and therefore its own context, but that is the server's
    guarantee, not this app's, and an app embedded in someone else's task must
    not leak an ID into whatever runs next. When an exception is unwinding,
    the binding is deliberately left in place - the server catches the
    exception *above* this block and only then logs the traceback, the one
    record the ID exists for (see "Request correlation" in
    docs/ARCHITECTURE.md).
    """
    request_id = (
        candidate
        if candidate is not None and _ACCEPTED_REQUEST_ID.fullmatch(candidate)
        else uuid.uuid4().hex
    )
    token = _request_id.set(request_id)
    yield request_id
    # Deliberately not in a finally: an exception unwinding through the yield
    # skips this reset, because uvicorn logs "Exception in ASGI application"
    # after this block has unwound and that record must carry this ID. Under
    # any conforming ASGI server the retained binding dies with the request's
    # own context; a host that catches the exception in a reused task keeps
    # the stale ID instead - the documented price of correlating the
    # traceback (see "Request correlation" in docs/ARCHITECTURE.md).
    _request_id.reset(token)


class RequestIDFilter(logging.Filter):
    """Stamp the current correlation ID onto every record reaching a handler."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Add ``request_id`` to the record and keep it."""
        # Through __dict__ because that is where Formatter reads %(request_id)s
        # from, and LogRecord declares no such attribute to assign to.
        record.__dict__["request_id"] = get_request_id()
        return True


def configure_logging(level: str) -> None:
    """
    Route every logger in the process through one request-ID-aware handler.

    Uvicorn installs handlers of its own on ``uvicorn``/``uvicorn.access`` and
    turns their propagation off, so its lines - including the access log, the
    one line per request that says *which* request - would otherwise bypass
    the formatter that prints the ID. Emptying those handler lists and turning
    propagation back on gives the process a single handler, which is also what
    keeps app and access lines in one correctly ordered stream instead of two.
    Their levels become ``NOTSET`` so they inherit the configured root level:
    ``LOG_LEVEL`` then means what it says, uvicorn's hardcoded INFO included.

    Called when ``app.main`` is imported - the executable boundary, and the
    ordering that lets this replace uvicorn's setup, because uvicorn
    configures its logging when its Config is constructed and imports the
    application module afterwards. Deliberately not called from anywhere
    ``create_app`` reaches: logging is deployment policy, and an embedding
    host keeps its own configuration unless it opts in by calling this.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            # Loggers already created by imported modules (app.lifecycle, ...)
            # must keep working; this reconfigures the process, not the world.
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIDFilter}},
            "formatters": {"default": {"format": LOG_FORMAT}},
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    # stdout, not stderr: logs are this process's event stream,
                    # not its error channel, and one stream cannot interleave
                    # out of order with itself the way two buffered ones do.
                    "stream": "ext://sys.stdout",
                    "formatter": "default",
                    "filters": ["request_id"],
                }
            },
            "loggers": {
                name: {"handlers": [], "propagate": True, "level": "NOTSET"}
                for name in ("uvicorn", "uvicorn.error", "uvicorn.access")
            },
            "root": {"handlers": ["default"], "level": level},
        }
    )
