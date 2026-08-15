"""
Operator-facing routes: orchestrator probes, and what this build is.

Everything here answers whoever is running the app rather than whoever is
calling it, which is why none of it sits under the /api prefix (see the
`router` comment below). The two groups are deliberately not one group: a probe
answers a question about *this instant* and drives an automated decision, while
/version answers a question about the artifact and drives a human one.
"""

from fastapi import APIRouter

from ..schemas import ProbeStatus, VersionInfo

# Stateless, so a module-level constant is safe for the same reason
# app.routers.api's is: include_router copies these routes into each app. The
# version route below holds a value that belongs to one app, so it is built by
# a factory instead - the split app.routers.api's comment describes.
#
# Deliberately *not* under the /api prefix. These answer an operator, not a
# caller of the product's API: an ingress may want to route or refuse them
# separately, and they must keep answering when every /api route is gone.
router = APIRouter()

LIVENESS_PATH = "/livez"
READINESS_PATH = "/readyz"
HEALTH_PATH = "/healthz"

# Every path answering the probe contract - 200 with {"status": "..."} - as a
# request carries it (no root_path). Named because the composition root exempts
# all of them from the Host allowlist *and* keeps all of them out of telemetry;
# tests/test_probes.py pins that each entry still names a route this router
# actually serves, so a stale entry cannot quietly exempt a path nothing
# answers. /version is deliberately not a member: it answers a different body,
# and it is worth tracing (see create_version_router).
PROBE_PATHS = (LIVENESS_PATH, READINESS_PATH, HEALTH_PATH)

# No trailing "z". The three names above are Kubernetes' own probe endpoints,
# copied verbatim, and the suffix they carry is the zpages convention for
# handlers reporting live *process state* (/healthz, /varz, /statusz). A build
# identity is not state - it is fixed for the life of the process - and the
# same Kubernetes API server serves it, like the Docker Engine API and etcd do,
# at a plain /version. Following the source of the other three names is what
# produces this one.
VERSION_PATH = "/version"


@router.get(LIVENESS_PATH)
async def livez() -> ProbeStatus:
    """
    Report that the process is alive - failing this means *restart me*.

    Answers a constant on purpose. Liveness must test the process and nothing
    reachable from it: an orchestrator responds to a failure here by killing
    the container, so a check that touches a database turns one slow
    dependency into every replica restarting at once - and a restart cannot
    repair a dependency anyway. Dependency checks belong in readyz.
    """
    return ProbeStatus(status="ok")


@router.get(READINESS_PATH)
async def readyz() -> ProbeStatus:
    """
    Report that this instance can serve traffic - failing this means *stop routing to me*.

    This is the seam for dependency checks: answer 503 while something this
    instance cannot serve without is unavailable, and the load balancer takes
    it out of rotation while the process keeps running and recovers on its
    own. This app depends on nothing, so today the answer is the same constant
    livez returns; the split exists so the check that eventually goes here
    lands on the route wired to de-routing rather than the one wired to a
    restart.
    """
    return ProbeStatus(status="ok")


@router.get(HEALTH_PATH)
async def healthz() -> ProbeStatus:
    """
    Report overall health, for tooling that probes this path by default.

    Kubernetes deprecated ``/healthz`` on its own API server in v1.16 and
    replaced it with the two routes above, for the reason their docstrings
    give: one answer cannot drive two decisions that fail in opposite
    directions. It is kept because the name is still what a good deal of
    tooling reaches for unprompted, and an endpoint that exists costs less
    than a probe that 404s. Point new deployments at ``/livez`` and
    ``/readyz``; if this ever has to stop being a constant, follow readiness
    rather than liveness - the wrong guess there restarts the fleet.
    """
    return ProbeStatus(status="ok")


def create_version_router(*, version: str, commit: str) -> APIRouter:
    """
    Create the build-identity route bound to one app's settings.

    A factory rather than a module-level router, because unlike the probes
    above this serves a value that belongs to a particular application: the
    same reason app.routers.pages is a factory, and the rule app.routers.api's
    comment states. The values arrive through this closure rather than off
    ``app.state``, which the composition root keeps as an introspection point
    for tests and embedding code rather than a runtime lookup.

    What this endpoint is *for* is answering "what is actually deployed right
    now" without registry access, a shell on the box, or trust in what a
    pipeline last reported it had rolled out. The composition root exempts it
    from the Host allowlist, so that question is answerable against an instance
    directly - a rollout check runs against a pod IP no allowlist can name in
    advance, exactly like a probe. Unlike a probe it stays *in* telemetry: it
    is asked occasionally rather than every few seconds, so it costs nothing to
    trace, and a span proving a rollout was verified is worth having.

    The trade-off in that exemption is that the release string is readable by
    anyone who can reach the instance. That is a deliberate distinction from
    the suppressed ``Server`` header (see "No `Server` header" in
    docs/ARCHITECTURE.md): that header hands out the stack and, with it, a list
    of published vulnerabilities to try, where this hands out a release number
    of this application's own that implies nothing about what it is built on.
    A deployment that disagrees drops VERSION_PATH from the exempt list in
    app.factory, which leaves the route answering only through the ingress.
    """
    router = APIRouter()

    @router.get(VERSION_PATH)
    async def version_info() -> VersionInfo:
        """Report the release and commit this build was made from."""
        return VersionInfo(version=version, commit=commit)

    return router
