"""Orchestrator probe routes against the live uvicorn server (see conftest.py)."""

import json
import urllib.error
import urllib.request

import pytest

from app.routers.probes import HEALTH_PATH, LIVENESS_PATH, PROBE_PATHS


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_answers(server: str, path: str) -> None:
    """
    Every advertised probe path answers 200 with the documented body.

    Parametrized over PROBE_PATHS rather than a literal list because that
    tuple is what the composition root exempts from the Host allowlist (see
    app.factory): an entry that stopped naming a real route would silently
    exempt a path nothing serves, and this turns that into a 404 here.
    """
    with urllib.request.urlopen(f"{server}{path}", timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {"status": "ok"}


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_is_not_under_the_api_prefix(path: str) -> None:
    """
    Probes answer an operator, not a caller of the product API.

    Pinned because moving them under /api would make them share the API's
    fate: a deployment that routes or blocks /api at the ingress would take
    the probes down with it, and every replica would fail its own liveness
    check as a result.
    """
    assert not path.startswith("/api")


def test_liveness_takes_no_dependency_on_the_application(server: str) -> None:
    """
    Liveness answers a constant, so nothing it touches can restart the fleet.

    The failure this guards is the one that makes liveness checks dangerous:
    a check reaching a database means a slow dependency is answered by killing
    every container at once, which cannot fix a dependency and removes the
    capacity that was still serving. If a future change gives this route work
    to do, that work belongs on /readyz instead - see app.routers.probes.
    """
    with urllib.request.urlopen(f"{server}{LIVENESS_PATH}", timeout=5) as resp:
        assert json.load(resp) == {"status": "ok"}


def test_legacy_health_path_matches_the_split_probes(server: str) -> None:
    """
    /healthz stays consistent with the routes that superseded it.

    Kubernetes deprecated /healthz in v1.16 in favour of /livez and /readyz;
    it is kept here for tooling that probes the name by default, which is only
    worth doing while it agrees with them.
    """
    with urllib.request.urlopen(f"{server}{HEALTH_PATH}", timeout=5) as legacy:
        legacy_body = json.load(legacy)
    with urllib.request.urlopen(f"{server}{LIVENESS_PATH}", timeout=5) as live:
        assert legacy_body == json.load(live)


@pytest.mark.parametrize("path", PROBE_PATHS)
def test_probe_reports_a_typed_status_in_the_schema(server: str, path: str) -> None:
    """
    The documented probe schema names its field rather than describing an object.

    ProbeStatus exists instead of dict[str, str] for this: the generated
    schema is what an operator reads to learn what the body means.
    """
    with urllib.request.urlopen(f"{server}/openapi.json", timeout=5) as resp:
        schema = json.load(resp)
    response = schema["paths"][path]["get"]["responses"]["200"]
    reference = response["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("/ProbeStatus")
    assert schema["components"]["schemas"]["ProbeStatus"]["required"] == ["status"]


def test_retired_health_route_is_gone(server: str) -> None:
    """
    /api/health no longer exists - the probes replaced it, they didn't join it.

    Pinned so the old path cannot quietly come back as a fourth way to ask the
    same question, and so a deployment still probing it fails loudly here
    rather than in production.
    """
    with pytest.raises(urllib.error.HTTPError) as excinfo:
        urllib.request.urlopen(f"{server}/api/health", timeout=5)
    assert excinfo.value.code == 404
