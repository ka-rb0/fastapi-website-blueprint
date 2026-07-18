# Commands

## Run everything

- `scripts/lint` <- every check in one run; keeps going on failure and
  summarizes at the end, so one run shows everything that is wrong
- `scripts/fix` <- every auto-fixer in one run
- `scripts/test` <- the full test suite with enforced coverage, as CI runs it

The sections below run the same tools one at a time.

## Dependencies

- `uv sync` <- everything in the dev group of pyproject.toml, at the exact
  versions in uv.lock (in the devcontainer this targets the system
  interpreter - no venv)
- `uv sync --only-group runtime` <- just what the app needs
- `uv lock --upgrade` <- refresh uv.lock to the latest versions by hand
  (Dependabot does this weekly)
- `npm ci` <- prettier + eslint at the exact versions in package-lock.json
  (only needed outside the devcontainer - the dev image bakes the tools into
  /opt/npm-tools and puts them on PATH, so `/workspace/node_modules` stays empty)

## Run Server

- `uvicorn app.main:app --host 0.0.0.0 --port $WEBSITE_INTERNAL_PORT --reload`

## Tests

- `pytest` (from `/workspace`) - API tests + Playwright E2E in headless
  Chromium; starts its own uvicorn server on port $WEBSITE_TEST_PORT, so the dev server
  can stay running.
- `pytest tests/test_api.py` <- skips the slower E2E suite
- `pytest --cov` <- what CI runs: adds app coverage (uvicorn subprocess
  included) and fails under the threshold in `[tool.coverage.report]`
- `coverage html` <- browsable per-line report in htmlcov/ (after `pytest --cov`)

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

### Markdownlint (Markdown docs)

- `markdownlint-cli2` <- globs and rule tweaks come from .markdownlint-cli2.jsonc
- `markdownlint-cli2 --fix` <- auto-fix

### Mypy (Python types)

- `mypy` <- targets come from pyproject.toml

## Security audits

- `npm audit --audit-level=high` <- npm advisory database vs package-lock.json
- `uv export --format requirements-txt --all-groups --no-emit-project --output-file /tmp/reqs.txt && pip-audit --disable-pip -r /tmp/reqs.txt`
  <- PyPA advisory database vs uv.lock
- `zizmor .github/workflows/` <- security lint of the GitHub Actions workflows

## Git hooks

- `.githooks/pre-push` blocks any push to main unless `scripts/lint` and
  `scripts/test` pass locally. The devcontainer activates it automatically
  (postCreateCommand in devcontainer.json).
- `git config core.hooksPath .githooks` <- one-time manual activation for
  clones used outside the devcontainer
