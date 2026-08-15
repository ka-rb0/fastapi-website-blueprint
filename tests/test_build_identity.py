"""
The chain that gets a release number from a git tag into a running container.

Four files have to agree for `GET /version` to answer with something true, and
no two of them are in the same language: the publish workflow names the build
arguments, the Dockerfile declares them and turns them into environment
variables, `app.config` reads those variables back, and only then does the
route serve them. Every link is a plain string on both sides, so a rename
anywhere breaks the chain silently - the app keeps booting and keeps answering,
just with a placeholder version forever. Nothing at run time can notice that,
because a placeholder is exactly what an untagged build is *supposed* to
report. These tests are the only thing standing between a typo and an image
that lies about which release it is.

The same shape as tests/test_node_version_consistency.py, and for the same
reason: a contract spanning files that no single test of behavior can hold
together.
"""

from pathlib import Path
from typing import Any

import yaml

from app.config import DEFAULT_COMMIT, DEFAULT_VERSION, Settings

from .helpers import distribution_args, distribution_environment

WORKFLOW = Path(__file__).parent.parent / ".github" / "workflows" / "publish.yml"

VERSION_ARG = "WEBSITE_VERSION"
COMMIT_ARG = "WEBSITE_COMMIT"


def _build_step() -> dict[str, Any]:
    """Return the publish workflow's image build step."""
    workflow = yaml.safe_load(WORKFLOW.read_text())
    step = next(
        (
            step
            for step in workflow["jobs"]["publish"]["steps"]
            if step.get("id") == "build"
        ),
        None,
    )
    assert step, "the publish workflow has no build step with id 'build'"
    build_step: dict[str, Any] = step
    return build_step


def _build_args() -> dict[str, str]:
    """Return the `--build-arg` values the publish workflow passes, by name."""
    declared = _build_step()["with"]["build-args"]
    return dict(
        line.split("=", 1) for line in declared.strip().splitlines() if line.strip()
    )


def test_the_image_declares_the_build_arguments_the_workflow_passes() -> None:
    """
    Neither side of the --build-arg contract can be renamed alone.

    A build argument the Dockerfile never declares is not an error - BuildKit
    warns and carries on - so the image would publish successfully and report
    the placeholder version for every release after the rename.
    """
    assert set(_build_args()) == {VERSION_ARG, COMMIT_ARG}
    assert set(distribution_args()) >= {VERSION_ARG, COMMIT_ARG}


def test_the_image_promotes_the_build_arguments_to_the_environment() -> None:
    """
    A build argument reaches the application only by becoming an ENV.

    ARG values exist during the build and are gone from the running container,
    so the ENV lines are the entire mechanism: without them the process would
    find nothing in its environment and fall back to the placeholder, with the
    version still visible in `docker history` and nowhere else.
    """
    environment = distribution_environment()

    assert environment[VERSION_ARG] == DEFAULT_VERSION
    assert environment[COMMIT_ARG] == DEFAULT_COMMIT


def test_the_untagged_defaults_are_the_ones_the_application_falls_back_to() -> None:
    """
    An image built with no --build-arg reports what a source checkout reports.

    Two independent statements of the same placeholder - the Dockerfile's ARG
    defaults and app.config's - and they are only harmless while they agree. If
    they drifted, "which builds are unreleased?" would have two answers
    depending on whether the deployment came from an image or a checkout.
    """
    settings = Settings()
    defaults = distribution_args()

    assert defaults[VERSION_ARG] == settings.version == DEFAULT_VERSION
    assert defaults[COMMIT_ARG] == settings.commit == DEFAULT_COMMIT


def test_the_workflow_sends_the_version_the_image_is_tagged_with() -> None:
    """
    The reported version comes from metadata-action, not straight off the ref.

    They differ in exactly the way that matters: `github.ref_name` is `v1.2.3`
    where the image tag is `1.2.3`, so sourcing the version from the ref would
    ship an image reporting a version string that matches no tag it was
    published under - and would report `refs/pull/7/merge`-shaped values on
    everything that is not a tag.
    """
    version = _build_args()[VERSION_ARG]

    assert "steps.meta.outputs.version" in version
    assert "github.ref_name" not in version


def test_the_workflow_sends_the_commit_that_was_built() -> None:
    """
    The commit is the triggering SHA, which is what makes non-tag builds identifiable.

    On a default-branch push the version degrades to the branch name, so this
    is the only field that can tell two builds of `:main` apart - the images
    most likely to be running when somebody asks what is deployed.
    """
    assert "github.sha" in _build_args()[COMMIT_ARG]
