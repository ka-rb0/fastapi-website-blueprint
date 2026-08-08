"""Application configuration loaded explicitly at the composition boundary."""

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass

from .observability import LogFormat

DEFAULT_MAX_BODY_BYTES = 1_000_000
DEFAULT_TRUSTED_HOSTS = ("localhost", "127.0.0.1")


@dataclass(frozen=True, slots=True, kw_only=True)
class Settings:
    """Validated, immutable settings for one application instance."""

    docs_enabled: bool = False
    trusted_hosts: tuple[str, ...] = DEFAULT_TRUSTED_HOSTS
    max_body_bytes: int = DEFAULT_MAX_BODY_BYTES
    # Validated here, but deliberately not consumed by create_app: the level is
    # applied by whoever owns the process (app.main hands it to
    # configure_logging), because logging is process-wide policy and a second
    # app in the same process cannot have a level of its own. Passing a level
    # to create_app therefore changes nothing on its own - it is validated at
    # boot and read at the entry point. See "Request correlation" and
    # "Lifespan" in docs/ARCHITECTURE.md.
    log_level: str = "INFO"
    # Applied by the same owner, for the same reason. Text is the code default
    # because that is what a developer tails; the distribution image sets
    # LOG_FORMAT=json in its environment, so production ships structured logs
    # without this file - or any file - being edited downstream. Typed as the
    # enum rather than a string, so the only validation needed is on the way
    # in from the environment (from_env below).
    log_format: LogFormat = LogFormat.TEXT

    def __post_init__(self) -> None:
        """Normalize human-entered values and reject unsafe configuration."""
        trusted_hosts = tuple(
            host.strip() for host in self.trusted_hosts if host.strip()
        )
        if not trusted_hosts:
            raise ValueError("trusted_hosts must contain at least one host")
        if self.max_body_bytes <= 0:
            raise ValueError("max_body_bytes must be greater than zero")

        log_level = self.log_level.upper()
        if log_level not in logging.getLevelNamesMapping():
            raise ValueError(f"unknown log level: {self.log_level}")

        object.__setattr__(self, "trusted_hosts", trusted_hosts)
        object.__setattr__(self, "log_level", log_level)

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        """
        Build settings from an environment mapping.

        Accepting a mapping makes configuration parsing deterministic in tests
        and avoids mutating process-wide environment variables.
        """
        values = os.environ if environ is None else environ
        raw_max_body_bytes = values.get(
            "WEBSITE_MAX_BODY_BYTES", str(DEFAULT_MAX_BODY_BYTES)
        )
        try:
            max_body_bytes = int(raw_max_body_bytes)
        except ValueError:
            raise ValueError(
                f"WEBSITE_MAX_BODY_BYTES must be an integer byte count,"
                f" got {raw_max_body_bytes!r}"
            ) from None
        # Strict on purpose: "true"/"yes" silently meaning *off* would be a
        # deployment footgun, so anything but the documented values refuses
        # to boot, like every other invalid setting.
        raw_docs_enabled = values.get("WEBSITE_ENABLE_DOCS", "0")
        if raw_docs_enabled not in ("0", "1", ""):
            raise ValueError(
                f"WEBSITE_ENABLE_DOCS must be '1' (on) or '0'/unset (off),"
                f" got {raw_docs_enabled!r}"
            )
        # Case-folded like LOG_LEVEL, and refused rather than silently falling
        # back to text: a typo that quietly un-structures production's logs
        # would only be discovered by the dashboard that stopped matching.
        raw_log_format = values.get("LOG_FORMAT", LogFormat.TEXT)
        try:
            log_format = LogFormat(raw_log_format.lower())
        except ValueError:
            raise ValueError(
                f"LOG_FORMAT must be one of {', '.join(LogFormat)},"
                f" got {raw_log_format!r}"
            ) from None
        return cls(
            docs_enabled=raw_docs_enabled == "1",
            trusted_hosts=tuple(
                values.get(
                    "WEBSITE_TRUSTED_HOSTS", ",".join(DEFAULT_TRUSTED_HOSTS)
                ).split(",")
            ),
            max_body_bytes=max_body_bytes,
            log_level=values.get("LOG_LEVEL", "INFO"),
            log_format=log_format,
        )
