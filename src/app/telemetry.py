"""OpenTelemetry traces and metrics: silent until a collector is configured."""

import os
import re
from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span

from .config import Settings
from .observability import get_request_id

# The correlation ID as a span attribute, so the value a user can read off the
# response (X-Request-ID) also finds the trace. Deliberately app-namespaced:
# the HTTP semantic conventions define no field for it, and borrowing one -
# `http.request.header.x-request-id` - would claim the ID arrived from the
# client, which is false whenever this app minted it.
REQUEST_ID_ATTRIBUTE = "request.id"

# The span and metric attribute names the instrumentation emits are a version
# choice, not a fixed set: the packages still default to the pre-stable HTTP
# conventions (http.method, a millisecond `http.server.duration`) and switch to
# the stable ones (http.request.method, a second-valued
# `http.server.request.duration`) only for a process that opts in here. This
# app opts in, because a standard template's whole value is that a metric name
# means the same thing on every service that carries it. `http/dup` - both
# name sets at once - is the migration setting for a fleet whose dashboards
# have not moved yet, and setting the variable explicitly still wins: this is a
# default, not an override.
SEMCONV_STABILITY_OPT_IN = "OTEL_SEMCONV_STABILITY_OPT_IN"
STABLE_HTTP_SEMCONV = "http"

# What Resource.create() reports when nothing named the service. Telemetry
# arriving under that name is the failure this app refuses to boot with:
# unnamed spans and metrics cannot be dashboarded, alerted on or told apart
# from every other unnamed service sharing the backend.
UNNAMED_SERVICE = "unknown_service"

# Only the HTTP/protobuf exporter is installed (see the dependency comment in
# pyproject.toml), so the standard protocol variables are validated rather than
# ignored: OTEL_EXPORTER_OTLP_PROTOCOL=grpc otherwise reads as accepted while
# every span keeps going out over HTTP to a port speaking gRPC.
SUPPORTED_OTLP_PROTOCOL = "http/protobuf"
OTLP_PROTOCOL_VARIABLES = (
    "OTEL_EXPORTER_OTLP_PROTOCOL",
    "OTEL_EXPORTER_OTLP_TRACES_PROTOCOL",
    "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL",
)


def create_providers() -> tuple[TracerProvider, MeterProvider]:
    """
    Build the SDK providers for both signals from the standard environment.

    Nothing is read from ``Settings`` here on purpose. Endpoint, headers,
    timeouts, compression, sampler, batch sizes and export intervals are all
    specified by OpenTelemetry, and the SDK constructors below already read
    them; restating any of them as a ``WEBSITE_*`` setting would invent a
    second vocabulary for values every operator, collector and vendor document
    already spells the standard way. What this function owns is the two things
    the environment cannot express: that both signals share one ``Resource``,
    so a trace and the metrics beside it describe the same service, and that a
    misconfiguration fails at boot instead of at the first dropped export.

    Both providers register an ``atexit`` flush of their own (the SDK's
    ``shutdown_on_exit`` default), which is why nothing in the lifespan drains
    them: a lifespan runs per application, and these are process-wide.
    """
    for variable in OTLP_PROTOCOL_VARIABLES:
        protocol = os.environ.get(variable, "").strip()
        if protocol and protocol != SUPPORTED_OTLP_PROTOCOL:
            raise ValueError(
                f"{variable} must be {SUPPORTED_OTLP_PROTOCOL!r} - only the"
                f" HTTP/protobuf OTLP exporter is installed; got {protocol!r}"
            )

    # Reads OTEL_SERVICE_NAME and OTEL_RESOURCE_ATTRIBUTES, so checking the
    # result covers both spellings of the same fact, plus anything a resource
    # detector contributed - which re-reading the variables here would not.
    resource = Resource.create()
    if resource.attributes.get(SERVICE_NAME) == UNNAMED_SERVICE:
        raise ValueError(
            "OTEL_SERVICE_NAME must name this service when telemetry is"
            f" enabled, or everything it exports arrives as {UNNAMED_SERVICE!r}"
        )

    tracer_provider = TracerProvider(resource=resource)
    # Batched, not simple: the exporter speaks HTTP, and a span flushed inline
    # would put a network round trip on the request that produced it.
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    return tracer_provider, meter_provider


def configure_telemetry(settings: Settings) -> None:
    """
    Install the process-wide providers, or do nothing at all.

    Called from ``app.main`` for the same reason ``configure_logging`` is, and
    it is the same reason twice: a tracer provider is one per process, so
    installing one is deployment policy that library code must not perform on
    behalf of its host. An application embedded in a service that already
    exports telemetry keeps that service's providers and its own trace context;
    it opts in by calling this itself.

    Doing nothing is the default and the whole of the off switch. Without a
    collector endpoint (see ``Settings.telemetry_enabled``) no provider is
    installed, so ``opentelemetry-api``'s no-op implementations stay in place -
    the instrumentation is not added to the application either, so a default
    deployment pays for neither.
    """
    if not settings.telemetry_enabled:
        return
    tracer_provider, meter_provider = create_providers()
    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)


def _record_request_id(span: Span, _scope: dict[str, Any]) -> None:
    """Put this request's correlation ID on its server span."""
    # RequestIDMiddleware wraps the whole framework stack, so the ID is already
    # bound by the time the span this hook receives is started. No is_recording
    # guard: a span the sampler dropped is a no-op object whose set_attribute
    # already does nothing, and the guard would only add an untaken branch.
    span.set_attribute(REQUEST_ID_ATTRIBUTE, get_request_id())


def _suffix_pattern(path: str) -> str:
    """Return a regex matching a URL that ends in ``path``, query string aside."""
    # A suffix match rather than an anchored one, because the URL the
    # instrumentation matches against carries whatever root_path the deployment
    # runs under (/prefix/livez), which is unknown here - the same reversal
    # problem app.middleware solves with get_route_path, on a string that has
    # already been turned back into a URL. The cost is that a route ending in
    # the same segment (/api/livez) would be excluded too.
    return rf"{re.escape(path)}(\?|$)"


def instrument_app(
    fastapi_app: FastAPI,
    *,
    exempt_paths: Iterable[str] = (),
    excluded_urls: Iterable[str] = (),
    tracer_provider: TracerProvider | None = None,
    meter_provider: MeterProvider | None = None,
) -> None:
    """
    Trace and measure every request this application handles.

    Instrumentation is per application, and providers are per process: passing
    them explicitly is what lets two differently configured apps in one process
    export to different places, and what lets a test read spans back out of an
    in-memory exporter. Omitted, they resolve to whatever ``configure_telemetry``
    installed.

    ``exempt_paths`` and ``excluded_urls`` name what is not worth recording.
    The probe routes are the reason it exists: three endpoints polled every few
    seconds by every orchestrator, container runtime and load balancer in front
    of the deployment, which between them would outnumber real traffic in the
    trace store and pull the latency histogram down toward a constant that
    tells nobody anything.

    Placed by ``FastAPIInstrumentor`` around FastAPI's *entire* middleware
    stack, error handling included, so a 500 is a failed span rather than a
    missing one. That still leaves it inside this app's own outer wrappers
    (see "Composition root" in docs/ARCHITECTURE.md): a request rejected by the
    body cap before routing is logged with its ID but never traced, the one
    response of this app's that telemetry does not see.
    """
    # Before the first instrumentation of the process, because the opt-in is
    # read once and cached: the instruments this call creates are named after
    # whatever it says now. setdefault, so an operator can still ask for
    # `http/dup` while their dashboards migrate.
    os.environ.setdefault(SEMCONV_STABILITY_OPT_IN, STABLE_HTTP_SEMCONV)
    FastAPIInstrumentor.instrument_app(
        fastapi_app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls=",".join(
            [*(_suffix_pattern(path) for path in exempt_paths), *excluded_urls]
        ),
        server_request_hook=_record_request_id,
        # One span per request, not three. The ASGI instrumentation otherwise
        # adds a child span per `receive` and `send` event, which for a server
        # rendering pages is per-request cost and storage buying detail nobody
        # reads; drop this argument to get them back for a streaming endpoint.
        exclude_spans=["receive", "send"],
    )
