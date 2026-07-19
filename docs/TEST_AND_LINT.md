# Test & Lint

## Checks / One-shot wrappers

- `scripts/lint` <- every check in one run; keeps going on failure and summarizes at
  the end, so one run shows everything that is wrong
- `scripts/fix` <- every auto-fixer in one run
- `scripts/test` <- the full test suite with enforced coverage (the same pytest
  invocation CI uses). One test needs outbound internet (the Swagger UI CDN) and
  skips with an explicit message when it is unreachable; `scripts/test --offline`
  deselects such tests (marked `online`) up front
- `scripts/audit` <- the security audits that need network access
  (pip-audit, npm audit, zizmor - the same ones CI runs)

## Individual tools

The one-shot wrappers above already run everything below; use these when you
want to run a single tool by itself.

- `pytest` <- from the repo root: API tests + Playwright E2E
- `ruff check . && ruff format --check .`
- `ruff check . --diff`
- `ruff check . --fix` <- auto-fix
- `ruff format .` <- auto-format
- `mypy` <- targets come from pyproject.toml
- `eslint .` <- ESLint (for JS)
- `eslint . --fix` <- auto-fix
- `codespell .` <- spell checker; skip list in `[tool.codespell]` in pyproject.toml
- `zizmor .github/workflows/` <- security lint of the CI workflows
  (`scripts/lint` runs it with `--offline`; the online audits need network
  access and a GH_TOKEN, so they live in `scripts/audit` and CI)
- `npm audit --audit-level=high` <- npm advisory database vs package-lock.json
- `uv export --format requirements-txt --all-groups --no-emit-project --output-file /tmp/reqs.txt && pip-audit --disable-pip -r /tmp/reqs.txt`
  <- PyPA advisory database vs uv.lock
- `prettier --check .` <- respects .gitignore
- `prettier --write .` <- auto-fix
- `markdownlint-cli2` <- globs and rule tweaks come from .markdownlint-cli2.jsonc
- `markdownlint-cli2 --fix` <- auto-fix
- `pytest -m 'not online'` <- the same deselection for a bare pytest run
