# Commands

## Dependencies

- `uv sync` <- everything in the dev group of pyproject.toml, at the exact
  versions in uv.lock (in the devcontainer this targets the system
  interpreter - no venv)
- `uv sync --only-group runtime` <- just what the app needs
- `uv lock --upgrade` <- refresh uv.lock to the latest versions by hand
  (Dependabot does this weekly)
- `npm ci` <- prettier + eslint at the exact versions in package-lock.json

## Run Server

- `uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload`

## Tests

- `pytest` (from `/workspace`) - API tests + Playwright E2E in headless
  Chromium; starts its own uvicorn server on port $WEBSITE_TEST_PORT, so the dev server
  can stay running.
- `pytest tests/test_api.py` <- skips the slower E2E suite

## Linting

### Prettier

- `prettier --check .` <- respects .gitignore
- `prettier --write .` <- auto-fix

### Codespell (spell checker)

- `codespell .` <- skip list comes from `[tool.codespell]` in pyproject.toml

### Ruff

- `ruff check .`
- `ruff check . --diff`
- `ruff check . --fix` <- auto-fix
- `ruff format .` <- auto-format

### ESLint (frontend JS)

- `eslint .`
- `eslint . --fix` <- auto-fix

### Mypy (Python types)

- `mypy` <- targets come from pyproject.toml

## Git hooks

- `git config core.hooksPath .githooks` <- one-time activation per clone;
  after that, `.githooks/pre-push` blocks any push to main unless the full
  CI suite (lint + tests) passes locally
- `git push --no-verify` <- emergency bypass of the hook
