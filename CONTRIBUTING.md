# Contributing

The bar for contributions is the same bar the template sets for the projects
built from it.

## Before you open a PR

- Run the checks CI runs - the commands are in
  [CHEATSHEET.md](docs/CHEATSHEET.md); the pre-push hook runs all of them when a
  push targets `main`.
- Cover new or changed behavior with a test.
- Update the docs when commands or setup steps change.

## Ground rules

- Dependencies are declared once and locked: python in `pyproject.toml` +
  `uv.lock`, npm tools in `package.json` + `package-lock.json`. Never add an
  unlocked install step.
- GitHub Actions stay pinned to commit SHAs, Docker base images to digests -
  Dependabot keeps the pins current.
- `main` only takes pull requests with green `lint` and `test` checks.
