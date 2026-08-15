"""Orchestrator probe routes against the live uvicorn server (see conftest.py)."""

import json
import urllib.error
import urllib.request

import pytest

from app.config import DEFAULT_COMMIT, DEFAULT_VERSION, Settings
from app.factory import create_app
from app.routers.probes import HEALTH_PATH, LIVENESS_PATH, PROBE_PATHS, VERSION_PATH

from .helpers import drive_get


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


def test_version_reports_the_build_the_app_was_configured_with() -> None:
    """
    /version answers with this instance's build, not a constant.

    Driven in process so the values under test are the ones a Settings carries,
    which is the whole contract: the image bakes WEBSITE_VERSION and
    WEBSITE_COMMIT into its environment (see .devcontainer/Dockerfile), config
    reads them, and the closure in create_version_router is what puts them on
    the wire. A route serving a module-level constant would pass every other
    test in this file and report the same version from every image ever built.
    """
    application = create_app(Settings(version="1.2.3", commit="a" * 40))

    response = drive_get(application, VERSION_PATH, host="localhost")

    assert response.status == 200
    assert json.loads(response.body) == {"version": "1.2.3", "commit": "a" * 40}


def test_an_untagged_build_says_so_rather_than_claiming_a_version(server: str) -> None:
    """
    A build from no release reports the placeholder, not an empty or invented version.

    This is what the suite's own server is - started from a source tree with no
    WEBSITE_VERSION in its environment - and what a developer's `docker build`
    produces. Reporting 0.0.0 is the honest answer, and it is a version no
    release will ever carry, so nothing downstream can mistake it for one.
    """
    with urllib.request.urlopen(f"{server}{VERSION_PATH}", timeout=5) as resp:
        assert resp.status == 200
        assert json.load(resp) == {
            "version": DEFAULT_VERSION,
            "commit": DEFAULT_COMMIT,
        }


def test_version_is_not_a_probe(server: str) -> None:
    """
    /version stays out of PROBE_PATHS, which is what that tuple is exempt as.

    Membership decides two unrelated things at once - the Host exemption and
    what telemetry never records - and /version wants only the first (see
    app.factory). Joining the tuple would silently drop it from every trace,
    and would break the probe contract the tests above assert over the whole
    tuple, since this route answers a different body.
    """
    assert VERSION_PATH not in PROBE_PATHS
    assert not VERSION_PATH.startswith("/api")

    with urllib.request.urlopen(f"{server}{VERSION_PATH}", timeout=5) as resp:
        assert "status" not in json.load(resp)


def test_version_reports_a_typed_body_in_the_schema(server: str) -> None:
    """
    The documented shape of /version names both of its fields.

    Same reasoning as the probe schema test above: this endpoint's readers are
    humans and deployment tooling, and the generated schema is where they find
    out that `commit` is a full SHA rather than an abbreviation.
    """
    with urllib.request.urlopen(f"{server}/openapi.json", timeout=5) as resp:
        schema = json.load(resp)
    response = schema["paths"][VERSION_PATH]["get"]["responses"]["200"]
    reference = response["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("/VersionInfo")
    assert schema["components"]["schemas"]["VersionInfo"]["required"] == [
        "version",
        "commit",
    ]


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
