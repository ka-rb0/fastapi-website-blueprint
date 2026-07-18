# FastAPI Website Blueprint (with an Agent-Ready Development Environment)

## Description

A FastAPI-based blueprint for a modern, minimalist website with light and
dark themes.

## Features

- Static frontend (vanilla HTML/CSS/JS, no build step) served by FastAPI.
- Light and dark themes: respects `prefers-color-scheme`, switchable in the
  UI (Light / Auto / Dark, where Auto follows the OS), persisted in
  `localStorage`, applied before first paint (no flash).
- Example API round trip: the "shout" form posts JSON to `/api/shout`
  (pydantic-validated) and renders the uppercased reply - copy this shape
  for real endpoints.
- API tests plus Playwright E2E tests against a live uvicorn server.
- Strict linting and type checking wired into CI.
- Security by default: same-origin CSP and hardening headers on every
  response, and security scanning in CI (pip-audit, npm audit, zizmor,
  CodeQL, dependency review).

## URLs

- [GitHub Repository](https://github.com/ka-rb0/fastapi-website-blueprint)

## Overview

The entire project, including its development environment, is containerized.

Human developers use Visual Studio Code with Dev Containers.

AI assistants run directly in the Dev Container and are allowed to install
and modify anything inside the ephemeral container as they please.

## Commands

For a list of common commands, see [CHEATSHEET.md](docs/CHEATSHEET.md).

## Dependencies

Declared once and locked everywhere:

- Python packages: the `[dependency-groups]` table of
  [pyproject.toml](pyproject.toml) (PEP 735), exact versions pinned in
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

## Tests & linting

One-shot wrappers (`scripts/lint` keeps going on failure and summarizes, so
one run shows everything that is wrong):

```sh
scripts/lint  # every check below in one run
scripts/fix   # every auto-fixer in one run
scripts/test  # the full test suite with enforced coverage, as CI runs it
```

Individual tools:

```sh
pytest  # from the repo root: API tests + Playwright E2E
ruff check . && ruff format --check .
mypy
eslint .
prettier --check .  # respects .gitignore
markdownlint-cli2  # globs + rule tweaks in .markdownlint-cli2.jsonc
codespell .  # skip list in [tool.codespell] in pyproject.toml
zizmor .github/workflows/  # security lint of the CI workflows
```

## Extras

- [For Agents & AI Assistants](AGENTS.md)
- [Documentation](docs/README.md)

## License

[MIT](LICENSE)
