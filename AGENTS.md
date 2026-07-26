# FastAPI Website Blueprint - Agent Notes

## Safety check - read this first

Before doing anything else, verify that you are inside the project's dev
container: the repo is mounted at `/workspace` and `/.dockerenv` exists.
If either check fails, you are running directly on the host machine - stop
immediately, do not read or modify anything, and tell the user to reopen
the project in the dev container.

## Background

You are in a dev container - do as you please. Just make sure that anything
you change without permission stays inside the container. The container is
ephemeral, so any changes outside `/workspace` may be lost on a rebuild!

## What this is

A FastAPI-based blueprint for a modern, minimalist website with light and
dark themes.
See [README.md](README.md) for the full feature description.

## Checks

- `scripts/lint` - every lint/format/type check in one run; keeps going on
  failure and summarizes, so one run shows everything that is wrong
- `scripts/fix` - every auto-fixer in one run
- `scripts/test` - the full test suite (the same pytest invocation CI uses)
- `scripts/audit` - the security audits that need network access (the same
  ones CI runs); run it when you touch dependencies or workflows

Run `scripts/lint` and `scripts/test` before declaring work done.

## Conventions

- Never compare `scope["path"]` or `request.url.path` against a route string
  (`"/docs"`, `"/api/"`, ...) directly. Both carry `root_path` prepended when
  the app runs behind a reverse proxy (e.g. `uvicorn --root-path /prefix`),
  so a bare string comparison silently breaks under any path-prefixed
  deployment (K8s Ingress, Azure/AWS path-based routing, the dev container's
  Caddy sidecar) while working fine unprefixed - this bit both the CSP
  middleware and the branded-404 handler in `src/app/main.py`. Always run the
  path through `get_route_path()` (`from starlette._utils import
get_route_path` - see the import comment in `src/app/main.py` for why that
  private module, not `starlette.routing`'s re-export, is the correct
  import) first, the same reversal FastAPI's own router applies before
  matching routes.
