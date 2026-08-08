"""Orchestrator probe routes."""

from fastapi import APIRouter

from ..schemas import ProbeStatus

# Stateless, so a module-level constant is safe for the same reason
# app.routers.api's is: include_router copies these routes into each app.
#
# Deliberately *not* under the /api prefix. These answer an operator, not a
# caller of the product's API: an ingress may want to route or refuse them
# separately, and they must keep answering when every /api route is gone.
router = APIRouter()

LIVENESS_PATH = "/livez"
READINESS_PATH = "/readyz"
HEALTH_PATH = "/healthz"

# Every path this router serves, as a request carries it (no root_path).
# Named because the composition root exempts all of them from the Host
# allowlist - see HostValidationMiddleware. tests/test_probes.py pins that
# each entry still names a route this router actually serves, so a stale
# entry cannot quietly exempt a path nothing answers.
PROBE_PATHS = (LIVENESS_PATH, READINESS_PATH, HEALTH_PATH)


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
