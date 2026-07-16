"""
Guard for the hand-mirrored Node.js major version.

engines.node in package.json is the single source of truth for the Node line:
CI reads it via setup-node's node-version-file. The dev image can't - its
node comes from the digest-pinned FROM node:<major>-slim line in
02_dev/Dockerfile (Dependabot bumps the digest, only a human bumps the major).
This test turns that Dockerfile's "must match engines.node" comment into an
enforced invariant. Pure file check - no server needed.
"""

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


def test_dev_image_node_major_matches_engines() -> None:
    """The FROM node:<major> pin in 02_dev/Dockerfile mirrors engines.node."""
    engines = json.loads((REPO_ROOT / "package.json").read_text())["engines"]["node"]
    match = re.fullmatch(r"(\d+)\.x", engines)
    assert match, f"engines.node is {engines!r}, expected the form '<major>.x'"
    engines_major = match.group(1)

    dockerfile = (
        REPO_ROOT / ".devcontainer" / "docker_files" / "02_dev" / "Dockerfile"
    ).read_text()
    match = re.search(r"^FROM node:(\d+)-slim@sha256:", dockerfile, re.MULTILINE)
    assert match, "FROM node:<major>-slim@sha256:... not found in 02_dev/Dockerfile"
    assert match.group(1) == engines_major
