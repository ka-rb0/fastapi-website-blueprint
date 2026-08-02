# Commands

## Dependencies

- `uv sync` <- the runtime deps plus everything in the dev group of
  pyproject.toml, at the exact versions in uv.lock (in the devcontainer this
  targets the system interpreter - no venv)
- `uv sync --no-default-groups` <- just what the app needs
  (`[project.dependencies]`)
- `uv lock --upgrade` <- refresh uv.lock to the latest versions by hand
  (Dependabot does this weekly)
- `npm ci` <- prettier + eslint + markdownlint-cli2 at the exact versions in
  package-lock.json (only needed outside the devcontainer - the dev image
  bakes the tools into /opt/npm-tools and puts them on PATH, so
  `/workspace/node_modules` stays empty)

## Run the server

The proxy-backed server starts with the Dev Container. Start the direct server
when you want unproxied HTTP as well.

- Direct:
  `uvicorn app.main:app --reload` (`UVICORN_HOST` and `UVICORN_PORT` come from
  Compose)
- Through Caddy: the `proxy-backend` Compose service runs Uvicorn with the
  same native `UVICORN_*` settings documented for production in
  [QUICKSTART.md](QUICKSTART.md).

## Tests

The everyday checks (`scripts/lint`, `scripts/test`, ...) are in
[Test & Lint](TEST_AND_LINT.md); the commands below are for targeted runs.

- `pytest` (from `/workspace`) <- API tests + Playwright E2E in headless
  Chromium; starts its own uvicorn servers on the inclusive port range
  $WEBSITE_TEST_PORT_MIN..$WEBSITE_TEST_PORT_MAX, so the dev server can stay
  running
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
