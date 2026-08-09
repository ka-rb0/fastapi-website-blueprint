"""
OpenTelemetry: standard names on the wire, nothing at all until it is asked for.

Three things are worth pinning here, and they fail independently. That the
export is *off* by default, because a blueprint that quietly opened a
connection to localhost:4318 would be a surprise in every project derived from
it. That what it emits when it is on carries the **stable** HTTP semantic
convention names - the whole reason to prefer a standard over a homegrown
counter is that `http.server.request.duration` means the same thing on every
service in the fleet, and the instrumentation still defaults to the pre-stable
spelling for anyone who does not opt in (see app.telemetry). And that the
chain actually reaches a collector: the in-process tests below read spans out
of an in-memory exporter, which proves the instrumentation but not the
transport, so the last test runs a real server against a real OTLP endpoint,
parses what arrived, and checks the server's own access line names that same
trace - the join an operator walks from a log search to a request's trace.
"""

import json
import logging
import os
import time
import urllib.request
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import NamedTuple

import pytest
from opentelemetry import metrics, trace
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

from app.config import OTLP_ENDPOINT_VARIABLES, Settings
from app.factory import create_app
from app.middleware import RequestIDMiddleware
from app.observability import (
    REQUEST_ID_HEADER,
    CorrelationFilter,
    JsonLogFormatter,
)
from app.routers.probes import PROBE_PATHS, READINESS_PATH
from app.telemetry import (
    OTLP_PROTOCOL_VARIABLES,
    REQUEST_ID_ATTRIBUTE,
    UNNAMED_SERVICE,
    configure_telemetry,
    create_providers,
)

from .conftest import next_test_port, run_server
from .helpers import drive_get, framework_app

HOST = "site.example"

# The metric an alert is written against, and the name it had before the HTTP
# conventions stabilized. Both are asserted on: the old one is what this app
# would emit by default, so its *absence* is the evidence that the opt-in in
# app.telemetry is doing something.
DURATION_METRIC = "http.server.request.duration"
LEGACY_DURATION_METRIC = "http.server.duration"

# The service name the exported telemetry must arrive under. Anything is fine
# except nothing: a resource with no service.name is what app.telemetry refuses
# to boot with.
SERVICE = "blueprint-under-test"


class Collected(NamedTuple):
    """The telemetry one module-wide pair of in-memory providers has gathered."""

    spans: InMemorySpanExporter
    metrics: InMemoryMetricReader
    tracer_provider: TracerProvider


@pytest.fixture(scope="module")
def collected() -> Generator[Collected]:
    """
    Install in-memory providers as this process's, for the whole module.

    Globals on purpose, rather than providers handed to `instrument_app`: the
    application under test is then built by `create_app` exactly as a
    deployment builds it, and the wiring in the composition root is part of
    what these tests cover. Nothing else in the suite produces telemetry, and a
    tracer provider can only be installed once per process, so this module owns
    the pair and clears the exporter between tests.
    """
    spans = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    # Simple, not batched: a test must not wait on an export interval.
    tracer_provider.add_span_processor(SimpleSpanProcessor(spans))
    reader = InMemoryMetricReader()
    meter_provider = MeterProvider(metric_readers=[reader])
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)
    yield Collected(spans, reader, tracer_provider)
    tracer_provider.shutdown()
    meter_provider.shutdown()


@pytest.fixture
def traced_app(collected: Collected) -> RequestIDMiddleware:
    """Build the application an exporting deployment builds, spans cleared."""
    collected.spans.clear()
    return create_app(Settings(trusted_hosts=(HOST,), telemetry_enabled=True))


def _metric_names(collected: Collected) -> set[str]:
    """Every metric name the in-memory reader has seen so far."""
    data = collected.metrics.get_metrics_data()
    assert data is not None
    return {
        metric.name
        for resource_metrics in data.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }


def test_a_request_becomes_one_span_named_after_its_route(
    traced_app: RequestIDMiddleware, collected: Collected
) -> None:
    """
    The span carries the route, not the URL, and the ID the client was handed.

    `http.route` is the templated path, which is what keeps a dashboard's
    grouping bounded - a per-URL label set grows with traffic. The correlation
    ID is the other half: a user reporting "request 3f2b… failed" hands over a
    value read off a response header, and this attribute is what turns that
    into a trace.
    """
    response = drive_get(traced_app, "/", host=HOST)

    assert response.status == 200
    (span,) = collected.spans.get_finished_spans()
    assert span.name == "GET /"
    assert span.attributes is not None
    assert span.attributes["http.request.method"] == "GET"
    assert span.attributes["http.route"] == "/"
    assert span.attributes["http.response.status_code"] == 200
    assert span.attributes["url.path"] == "/"
    assert (
        span.attributes[REQUEST_ID_ATTRIBUTE]
        == response.headers[REQUEST_ID_HEADER.lower()]
    ), "the span and the response name different requests"


def test_the_latency_histogram_carries_the_stable_metric_name(
    traced_app: RequestIDMiddleware, collected: Collected
) -> None:
    """
    Requests are measured as `http.server.request.duration`, in seconds.

    The pre-stable spelling must be absent, not merely accompanied: it is what
    the instrumentation emits without the opt-in this app makes, it is
    measured in milliseconds, and a fleet where half the services report each
    name is one where no dashboard can average them.
    """
    drive_get(traced_app, "/", host=HOST)

    names = _metric_names(collected)
    assert DURATION_METRIC in names
    assert LEGACY_DURATION_METRIC not in names, "the stable opt-in stopped applying"


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_traffic_is_recorded_nowhere(
    traced_app: RequestIDMiddleware, collected: Collected, path: str
) -> None:
    """
    Orchestrator probes leave no span behind.

    Every layer in front of a deployment polls these - the container runtime's
    healthcheck, the kubelet's liveness and readiness probes, a load balancer's
    own check - several times a minute, forever. Traced, they would outnumber
    real requests in the trace store and drag the latency histogram toward the
    cost of returning a constant.
    """
    assert drive_get(traced_app, path, host=HOST).status == 200

    assert collected.spans.get_finished_spans() == ()


def test_an_unhandled_exception_leaves_a_failed_span(
    traced_app: RequestIDMiddleware, collected: Collected
) -> None:
    """
    A 500 is a failed span, not a missing one.

    This pins where the instrumentation sits: outside FastAPI's own error
    handling, so the span is still open when `ServerErrorMiddleware` turns the
    exception into a response. Inside it, the request that most needs a trace
    would be the one request without one.
    """

    async def boom(request: Request) -> Response:
        raise RuntimeError("kaboom")

    # Inserted at the front for the reason tests/failing_app.py gives: the
    # StaticFiles mount at "/" matches every path, so an appended route would
    # answer 404 and this test would assert nothing.
    framework_app(traced_app).router.routes.insert(0, Route("/boom", boom))

    with pytest.raises(RuntimeError):
        drive_get(traced_app, "/boom", host=HOST)

    (span,) = collected.spans.get_finished_spans()
    assert span.status.status_code is StatusCode.ERROR
    # The cause, as an exception event - the semantic convention's shape, and
    # the same information the traceback in the log carries, on the other side
    # of the join.
    (event,) = span.events
    assert event.name == "exception"
    assert event.attributes is not None
    assert event.attributes["exception.type"] == "RuntimeError"
    assert event.attributes["exception.message"] == "kaboom"


def test_an_application_without_a_collector_is_not_instrumented(
    collected: Collected,
) -> None:
    """
    The default build records nothing, rather than recording into a void.

    Off has to mean *absent*: a middleware that starts and ends a span per
    request only to drop it is cost with no product. The providers installed
    for this module make the difference observable - an instrumented app would
    export into them.
    """
    collected.spans.clear()
    application = create_app(Settings(trusted_hosts=(HOST,)))

    assert drive_get(application, "/", host=HOST).status == 200

    assert collected.spans.get_finished_spans() == ()


def test_a_log_record_inside_a_span_joins_the_trace(collected: Collected) -> None:
    """
    JSON log lines carry `trace_id`/`span_id` while a span is current.

    That is the join between the two halves of this app's observability: the
    log line explaining *what* went wrong, and the trace showing *where* the
    request spent its time. The fields are absent - not zero - outside a span,
    because an all-zero trace ID is a value a backend indexes and joins on.
    """
    record = logging.LogRecord(
        name="app.demo",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="handled",
        args=(),
        exc_info=None,
    )
    tracer = collected.tracer_provider.get_tracer(__name__)
    with tracer.start_as_current_span("unit") as span:
        CorrelationFilter().filter(record)
        expected = span.get_span_context()
    traced = json.loads(JsonLogFormatter().format(record))

    untraced_record = logging.LogRecord(
        name="app.demo",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="started",
        args=(),
        exc_info=None,
    )
    CorrelationFilter().filter(untraced_record)
    untraced = json.loads(JsonLogFormatter().format(untraced_record))

    assert traced["trace_id"] == format(expected.trace_id, "032x")
    assert traced["span_id"] == format(expected.span_id, "016x")
    assert "trace_id" not in untraced
    assert "span_id" not in untraced


def test_telemetry_stays_off_until_a_collector_is_named() -> None:
    """No endpoint, no export - and no instrumentation to pay for."""
    assert Settings.from_env({}).telemetry_enabled is False


@pytest.mark.parametrize("variable", OTLP_ENDPOINT_VARIABLES)
def test_any_otlp_endpoint_variable_turns_telemetry_on(variable: str) -> None:
    """The per-signal variables count too: traces and metrics may be split."""
    settings = Settings.from_env({variable: "http://collector.internal:4318"})

    assert settings.telemetry_enabled is True


@pytest.mark.parametrize("value", ["true", "TRUE", " True "])
def test_the_standard_kill_switch_turns_telemetry_back_off(value: str) -> None:
    """
    `OTEL_SDK_DISABLED` wins over a configured endpoint.

    It is the specification's own switch, which is why this app grows none of
    its own: an operator silencing telemetry fleet-wide sets one variable that
    every OpenTelemetry SDK already understands, and does not have to discover
    a `WEBSITE_*` flag per service.
    """
    settings = Settings.from_env(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            "OTEL_SDK_DISABLED": value,
        }
    )

    assert settings.telemetry_enabled is False


@pytest.mark.parametrize("value", ["1", "yes", "false", ""])
def test_only_the_specified_spelling_disables_the_sdk(value: str) -> None:
    """
    Anything but "true" leaves telemetry on, which is the specification's rule.

    Deliberately the opposite of how `WEBSITE_ENABLE_DOCS=yes` is treated: the
    OTEL_* variables belong to OpenTelemetry, so they are read by its rules
    rather than by this app's stricter house style. Refusing to boot on a
    value the specification defines as false would make this app the one
    service in a fleet that cannot start.
    """
    settings = Settings.from_env(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector:4318",
            "OTEL_SDK_DISABLED": value,
        }
    )

    assert settings.telemetry_enabled is True


def test_extra_excluded_urls_are_read_from_the_standard_variable() -> None:
    """A deployment's own exclusions are additions, never a replacement."""
    settings = Settings.from_env(
        {"OTEL_PYTHON_EXCLUDED_URLS": " /metrics , /internal/.* ,"}
    )

    assert settings.telemetry_excluded_urls == ("/metrics", "/internal/.*")


def test_both_signals_describe_one_named_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Traces and metrics share a resource, so a backend joins them by themselves.

    Two resources built independently would be equal today and drift the first
    time a detector or an attribute is added to one call and not the other -
    at which point a service's traces and its metrics stop being the same
    service to anything reading them.
    """
    monkeypatch.setenv("OTEL_SERVICE_NAME", SERVICE)

    tracer_provider, meter_provider = create_providers()
    try:
        resource = tracer_provider.resource
        assert resource.attributes[SERVICE_NAME] == SERVICE
        assert meter_provider._sdk_config.resource is resource
    finally:
        tracer_provider.shutdown()
        meter_provider.shutdown()


def test_an_unnamed_service_refuses_to_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Exporting as "unknown_service" is a failure worth failing the deploy for.

    It is not a degraded state that can be noticed later: the telemetry lands
    in the backend under a name shared with every other service nobody named,
    where it cannot be dashboarded, alerted on, or told apart from theirs.
    """
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_RESOURCE_ATTRIBUTES", raising=False)

    with pytest.raises(ValueError, match=rf"OTEL_SERVICE_NAME.*{UNNAMED_SERVICE}"):
        create_providers()


@pytest.mark.parametrize("variable", OTLP_PROTOCOL_VARIABLES)
def test_an_unsupported_otlp_protocol_refuses_to_boot(
    monkeypatch: pytest.MonkeyPatch, variable: str
) -> None:
    """
    Asking for gRPC fails loudly instead of exporting over HTTP anyway.

    Only the HTTP/protobuf exporter is installed. Ignoring the variable would
    leave a deployment that configured gRPC pointing an HTTP exporter at a port
    speaking gRPC - visible only as exports that never arrive.
    """
    monkeypatch.setenv("OTEL_SERVICE_NAME", SERVICE)
    monkeypatch.setenv(variable, "grpc")

    with pytest.raises(ValueError, match=rf"{variable}.*'grpc'"):
        create_providers()


def test_configuring_telemetry_while_it_is_off_installs_nothing(
    collected: Collected,
) -> None:
    """The entry point calls this unconditionally; disabled means untouched."""
    installed = trace.get_tracer_provider()

    configure_telemetry(Settings())

    assert trace.get_tracer_provider() is installed


class _Export(NamedTuple):
    """One OTLP request a collector received."""

    path: str
    content_type: str
    body: bytes


@contextmanager
def _otlp_collector(port: int) -> Generator[list[_Export]]:
    """Serve an OTLP/HTTP endpoint on `port`, recording what is posted to it."""
    exports: list[_Export] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers.get("content-length", 0)))
            exports.append(
                _Export(self.path, self.headers.get("content-type", ""), body)
            )
            # An empty body *is* a well-formed ExportTraceServiceResponse:
            # protobuf encodes a message with no fields set as zero bytes.
            self.send_response(200)
            self.send_header("content-type", "application/x-protobuf")
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Stay quiet - this handler's traffic is not the test's output."""

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield exports
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _await_export(exports: list[_Export], path: str) -> _Export:
    """Return the first export posted to `path`, waiting for the batch to flush."""
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        for export in exports:
            if export.path == path:
                return export
        time.sleep(0.1)
    raise AssertionError(f"nothing was exported to {path} within 20s")


def test_a_running_server_exports_to_a_real_collector(tmp_path: Path) -> None:
    """
    The whole chain, end to end: uvicorn, `app.main`, OTLP over HTTP, a listener.

    The in-memory tests above stop at the instrumentation. This one is what
    proves the rest of it - that the entry point installs providers at all,
    that the exporter reaches a collector without a code change, and that what
    arrives on the wire carries the service name and the route. It parses the
    protobuf rather than checking that bytes showed up, because "a POST
    happened" would also pass if the payload were empty.

    The server's own log stream is read back for the other half of the claim:
    the access line - the one line per request - names the very trace the
    collector received, which is the join an operator actually walks, from a
    log search to the trace of the request that produced it. Uvicorn writes
    that line from the `send()` call the instrumentation is still wrapping,
    which is why it has the IDs at all; the probe lines beside it have none,
    because that path is excluded from tracing entirely.
    """
    collector_port = next_test_port()
    log_path = tmp_path / "server.log"
    with _otlp_collector(collector_port) as exports:
        environment = {
            **os.environ,
            "LOG_FORMAT": "json",
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{collector_port}",
            "OTEL_SERVICE_NAME": SERVICE,
            # Milliseconds. The defaults are a 5-second batch delay and a
            # 60-second metric interval - correct for a deployment, and far
            # longer than a test should wait for the same code path.
            "OTEL_BSP_SCHEDULE_DELAY": "200",
            "OTEL_METRIC_EXPORT_INTERVAL": "500",
        }
        with (
            log_path.open("wb") as sink,
            run_server(next_test_port(), environment, output=sink) as base_url,
        ):
            urllib.request.urlopen(f"{base_url}/", timeout=5).close()

        trace_request = ExportTraceServiceRequest.FromString(
            _await_export(exports, "/v1/traces").body
        )
        metrics_request = ExportMetricsServiceRequest.FromString(
            _await_export(exports, "/v1/metrics").body
        )

    services = {
        attribute.value.string_value
        for resource_spans in trace_request.resource_spans
        for attribute in resource_spans.resource.attributes
        if attribute.key == SERVICE_NAME
    }
    spans = [
        span
        for resource_spans in trace_request.resource_spans
        for scope_spans in resource_spans.scope_spans
        for span in scope_spans.spans
    ]
    metric_names = {
        metric.name
        for resource_metrics in metrics_request.resource_metrics
        for scope_metrics in resource_metrics.scope_metrics
        for metric in scope_metrics.metrics
    }

    assert services == {SERVICE}
    assert [span.name for span in spans] == ["GET /"], (
        "the readiness poll that started this server was traced as well"
    )
    assert DURATION_METRIC in metric_names

    access_lines = [
        record
        for line in log_path.read_text().splitlines()
        if (record := json.loads(line))["logger"] == "uvicorn.access"
    ]
    (traced_line,) = [
        record for record in access_lines if '"GET / HTTP' in record["message"]
    ]
    probe_lines = [
        record for record in access_lines if READINESS_PATH in record["message"]
    ]
    assert traced_line["trace_id"] == spans[0].trace_id.hex()
    assert probe_lines, "the readiness poll left no access line to check"
    assert all("trace_id" not in record for record in probe_lines)
