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
