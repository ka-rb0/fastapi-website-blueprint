# Security Policy

## Reporting a vulnerability

Please do not open a public issue for security problems.

Use GitHub's private vulnerability reporting instead: on the repository page,
go to **Security → Report a vulnerability**. You should get a response within a month.

## Supported versions

This is a template, not a released product: only the current `main` branch is
supported. Forks maintain their own copies.

## Scope

In scope: the FastAPI app, the static frontend, the Docker images, the CI
workflows, and the dev container configuration - anything a project built
from this template inherits.

Out of scope: vulnerabilities in third-party dependencies that are already
fixed upstream (Dependabot and the CI audits handle those - but a report is
welcome if the template pins a vulnerable version and CI misses it).
