# Commands

## Dependencies

- `uv sync` <- everything in the dev group of pyproject.toml, at the exact
  versions in uv.lock (in the devcontainer this targets the system
  interpreter - no venv)
- `uv sync --only-group runtime` <- just what the app needs
- `uv lock --upgrade` <- refresh uv.lock to the latest versions by hand
  (Dependabot does this weekly)
- `npm ci` <- prettier + eslint + markdownlint-cli2 at the exact versions in package-lock.json
  (only needed outside the devcontainer - the dev image bakes the tools into
  /opt/npm-tools and puts them on PATH, so `/workspace/node_modules` stays empty)

## Run Server

- `uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload`

## Tests

### Basic Tests & Linting

- [Basic Tests & Lint Commands](TEST_AND_LINT.md)

### Targeted/Advanced Tests

- `pytest` (from `/workspace`) - API tests + Playwright E2E in headless
  Chromium; starts its own uvicorn server on port $WEBSITE_TEST_PORT, so the dev server
  can stay running.
- `pytest tests/test_api.py` <- skips the slower E2E suite
- `pytest --cov` <- what CI runs: adds app coverage (uvicorn subprocess
  included) and fails under the threshold in `[tool.coverage.report]`
- `coverage html` <- browsable per-line report in htmlcov/ (after `pytest --cov`)

## Git hooks

- `.githooks/pre-push` blocks any branch push unless `scripts/lint` and
  `scripts/test` pass locally. The devcontainer activates it automatically
  (postCreateCommand in devcontainer.json).
- `git config core.hooksPath .githooks` <- one-time manual activation for
  clones used outside the devcontainer
