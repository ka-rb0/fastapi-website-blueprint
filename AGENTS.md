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
Individual per-tool commands are in [docs/CHEATSHEET.md](docs/CHEATSHEET.md).
