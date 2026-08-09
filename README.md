# FastAPI Website Blueprint (with an Agent-Ready Development Environment)

<!-- ?branch=main so the CI badge reports main's latest push run, not the
     most recent PR run - the badge is the trust signal for the default
     branch. The issues badge comes from shields.io (GitHub serves no native
     badge for those); it reads the public GitHub API, so they update on
     their own. -->

[![CI](https://github.com/ka-rb0/fastapi-website-blueprint/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ka-rb0/fastapi-website-blueprint/actions/workflows/ci.yml?query=branch%3Amain)
[![Open issues](https://img.shields.io/github/issues/ka-rb0/fastapi-website-blueprint)](https://github.com/ka-rb0/fastapi-website-blueprint/issues)

## Description

A FastAPI-based blueprint for a modern, minimalist website with light and
dark themes.

## Features

- Server-rendered pages (Jinja2 templates sharing one base layout) plus
  static assets (vanilla CSS/JS, no build step), all served by FastAPI.
  Shared values - design tokens from the CSS, API limits from Python - are
  injected at render time instead of hand-mirrored.
- Light and dark themes: respects `prefers-color-scheme`, switchable in the
  UI (Light / System / Dark, where System follows the OS), persisted in
  `localStorage`, applied before first paint (no flash).
- Example API round trip: the "shout" form posts JSON to `/api/shout`
  (pydantic-validated) and renders the uppercased reply - copy this shape
  for real endpoints.
- Orchestrator probes that keep liveness and readiness apart: `/livez`
  (failing means _restart me_), `/readyz` (failing means _stop routing to
  me_) and `/healthz` as the legacy alias. Both decisions get their own
  route, so the dependency check you add later lands on the one wired to
  de-routing rather than the one wired to a restart.
- API tests plus Playwright E2E tests against a live uvicorn server.
- A development-only Caddy sidecar for exercising local HTTPS, forwarded
  headers, and a stripped URL prefix against a second reload-enabled Uvicorn
  process while preserving direct HTTP access.
- Request correlation: every request gets an `X-Request-ID` (accepted from
  the caller when usable, minted otherwise), echoed on the response and
  printed on every log line - uvicorn's access log included.
- OpenTelemetry traces and metrics under the stable HTTP semantic-convention
  names, off until you point `OTEL_EXPORTER_OTLP_ENDPOINT` at a collector -
  no code change, no home-grown metric names, and probe traffic excluded so
  it can't drown the real thing.
- Strict linting and type checking wired into CI.
- Security by default: same-origin CSP and hardening headers on every
  response, a Host-header allowlist, a transport-level request-body cap,
  and security scanning in CI (pip-audit, npm audit, zizmor, CodeQL,
  dependency review).

## Overview

The entire project, including its development environment, is containerized.

Human developers use Visual Studio Code with Dev Containers.

AI assistants run directly in the Dev Container and are allowed to install
and modify anything inside the ephemeral container as they please.

The Python application uses an explicit composition root:
`app.create_app(Settings(...))` creates an independent ASGI application,
while `app.main:app` is the environment-configured Uvicorn entry point.
Configuration, lifecycle, middleware, schemas, templates, exception handlers,
and routers live in focused modules under `src/app`. The reasoning behind
the non-obvious decisions (middleware ordering, CSP derivation, `root_path`
handling, ...) is recorded in [ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Commands

- For a list of common commands, see [CHEATSHEET.md](docs/CHEATSHEET.md).
- [Test & Lint](docs/TEST_AND_LINT.md)

## Dependencies

Declared once and locked everywhere:

- Python packages: `[project.dependencies]` (runtime, PEP 621) and the
  `[dependency-groups]` table (dev tooling, PEP 735) of
  [pyproject.toml](pyproject.toml), exact versions pinned in
  [uv.lock](uv.lock). Install manually with `uv sync` (runtime + all dev
  tools).
- npm-based lint tools (prettier, eslint, markdownlint):
  [package.json](package.json), pinned in
  [package-lock.json](package-lock.json). Install with `npm ci`.
- Docker base images and GitHub Actions: pinned by tag / commit SHA where
  they are used.

The devcontainer images bake everything in, and Dependabot
([dependabot.yml](.github/dependabot.yml)) sends weekly PRs to keep all of
the pins current.

## Extras

- [For Agents & AI Assistants](AGENTS.md)
- [Documentation](docs/README.md)

## URLs

- [GitHub Repository](https://github.com/ka-rb0/fastapi-website-blueprint)

## License

[MIT](LICENSE)
