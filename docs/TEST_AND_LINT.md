# Test & Lint

## Checks / One-shot wrappers

- `scripts/lint` <- every check in one run; keeps going on failure and
  summarizes at the end, so one run shows everything that is wrong
- `scripts/fix` <- every auto-fixer in one run
- `scripts/test` <- the full test suite with enforced coverage (the same
  pytest invocation CI uses)
- `scripts/audit` <- the security audits that need network access (the same
  ones CI runs) (pip-audit, npm audit, zizmor)

## Individual tools (for reference only)

The sections below run the same tools as the one-shot wrappers (`scripts/lint`,
`scripts/fix`, `scripts/test`, `scripts/audit`) but one at a time, this
is for reference only.

- `pytest` # from the repo root: API tests + Playwright E2E
- `ruff check . && ruff format --check .`
- `ruff check . --diff`
- `ruff check . --fix` <- auto-fix
- `ruff format .` <- auto-format
- `mypy` <- targets come from pyproject.toml
- `eslint .` <- ESLint (for JS)
- `eslint . --fix` <- auto-fix
- `codespell .` # (spell checker) skip list in [tool.codespell] in pyproject.toml
- `zizmor .github/workflows/` # security lint of the CI workflows
- `npm audit --audit-level=high` <- npm advisory database vs package-lock.json
- `uv export --format requirements-txt --all-groups --no-emit-project --output-file /tmp/reqs.txt && pip-audit --disable-pip -r /tmp/reqs.txt`
  <- PyPA advisory database vs uv.lock
  (scripts/lint runs its offline subset; GH_TOKEN enables the online audits)
- `prettier --check .` <- respects .gitignore
- `prettier --write .` <- auto-fix
- `markdownlint-cli2` <- globs and rule tweaks come from .markdownlint-cli2.jsonc
- `markdownlint-cli2 --fix` <- auto-fix
