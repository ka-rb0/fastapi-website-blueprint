"""Request and response schemas for the public API."""

from pydantic import BaseModel, Field

MIN_SHOUT_LENGTH = 1
MAX_SHOUT_LENGTH = 1_000


class ProbeStatus(BaseModel):
    """
    Reply returned by the probe routes in ``app.routers.probes``.

    A model rather than ``dict[str, str]`` so the generated schema names the
    field instead of describing "an object of strings": orchestrators decide on
    the status code alone, but the body is documented surface that humans and
    dashboards read.
    """

    status: str


class VersionInfo(BaseModel):
    """
    Reply returned by ``GET /version`` in ``app.routers.probes``.

    Two fields because one does not answer the question on every build. The
    release tag is what a human asks for and what a changelog is written
    against, but a rolling default-branch image reports its version as the
    branch name - so the commit is what makes "which build is this?" answerable
    for the images most likely to be running when somebody needs to know. Both
    are unabbreviated: the full SHA pastes straight into ``git show``.

    Mirrors the two fields the Kubernetes API server puts at its own
    ``/version`` (``gitVersion``, ``gitCommit``), under names that do not
    presume the VCS.
    """

    version: str
    commit: str


class ShoutPayload(BaseModel):
    """Body accepted by ``POST /api/shout``."""

    text: str = Field(min_length=MIN_SHOUT_LENGTH, max_length=MAX_SHOUT_LENGTH)


class ShoutReply(BaseModel):
    """
    Reply returned by ``POST /api/shout``.

    Input and output use distinct models because uppercasing can lengthen text
    (for example, ``"ß".upper() == "SS"``).
    """

    text: str
