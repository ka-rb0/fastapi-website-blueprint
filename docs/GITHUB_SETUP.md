# GitHub repository setup (one-time)

The files in the repo configure CI and Dependabot automatically, but a few
protections live in GitHub's **settings** and must be enabled once by hand.

Everything below is **free for public repositories**. Items marked 💰 cost
money on private repos (they need paid GitHub Advanced Security) - if you
clone/fork this template and make your copy **private**, skip or disable
those items as noted, otherwise the affected CI jobs will fail.

## 1. Import the two rulesets

**Settings → Rules → Rulesets → New ruleset → Import a ruleset**, once per
file.

[.github/rulesets/protect-main.json](../.github/rulesets/protect-main.json)
enforces on `main`:

- no deletion, no force-push
- changes arrive via pull request (0 required approvals - solo-maintainer friendly)
- the `lint` and `test` checks must pass, and the branch must be up to date
  with `main` when it merges.

[.github/rulesets/protect-tags.json](../.github/rulesets/protect-tags.json)
enforces on `v*` tags:

- no deletion, no force-push - a published release tag cannot be repointed at
  different code afterwards, which would otherwise let `v1.2.3` and the image
  built from it disagree
- the name must parse as `v<major>.<minor>.<patch>`, optionally with a
  prerelease suffix - the same shape
  [publish.yml](../.github/workflows/publish.yml) triggers on, so a typo'd tag
  is rejected instead of silently publishing nothing.

Branch protection alone does not cover releases: `:latest` comes from a tag,
and a tag can be cut on any commit. `publish.yml` closes that half by refusing
to publish a tag whose commit is not on `main`.

Note: with the branch ruleset active, GitHub rejects direct pushes to `main` -
open a PR instead. The [pre-push hook](../.githooks/pre-push) stays useful as a
local safety net for clones that never import the ruleset.

## 2. Enable secret scanning + push protection

**Settings → Advanced Security**: enable **Secret scanning** and
**Push protection**. Scanning alerts on committed credentials; push
protection blocks them before they ever reach the repo.

💰 Private repos: needs paid Secret Protection - skip this on a private fork.

## 3. Enable private vulnerability reporting

**Settings → Advanced Security → Private vulnerability reporting**: enable.
This is the reporting channel [SECURITY.md](../SECURITY.md) points people to.

Private repos: not available - document a contact address in SECURITY.md
instead.

## 4. Enable Dependabot alerts

**Settings → Advanced Security → Dependabot**: enable **Dependabot alerts**
(and **grouped security updates** if you like). Version updates are already
configured by [dependabot.yml](../.github/dependabot.yml); alerts add
notifications when a _currently pinned_ dependency gets a CVE. Free on all
repos.

## 5. Code scanning - nothing to click, but private forks beware

These run from checked-in workflow files, so they work as soon as the repo
exists - but they are only free on public repos:

- 💰 [codeql.yml](../.github/workflows/codeql.yml) - CodeQL static analysis.
  On a private fork, delete the workflow or disable it in the Actions tab.
- 💰 the `dependency-review` job in [ci.yml](../.github/workflows/ci.yml) -
  flags PRs that introduce vulnerable dependencies. Advisory by design: the
  ruleset requires only `lint` and `test`, so a red run shows on the PR but
  can still be merged - the required `lint` job's lockfile audits already
  block vulnerable pinned dependencies, and staying non-required keeps an
  escape hatch for merging past a known, accepted advisory. On a private
  fork, delete the job.

The other CI audits (`pip-audit`, `npm audit`, `zizmor`) query public
advisory databases and are free everywhere - keep them.
[audit.yml](../.github/workflows/audit.yml) re-runs those audits on a weekly
schedule, so advisories published between pushes still surface; it is also
free everywhere.

## 6. Container images - nothing to click, two things to know

[publish.yml](../.github/workflows/publish.yml) pushes the `distribution`
image to `ghcr.io/<owner>/<repo>` using the workflow's own `GITHUB_TOKEN`,
so there is no registry secret to create. See
[.devcontainer/README.md](../.devcontainer/README.md) for the tags each
trigger publishes. Two settings only matter after the first successful push,
because GitHub creates the package then:

- **Visibility.** A new package is private, whatever the repo is. To let
  anyone `docker pull` it: package page → **Package settings** →
  **Change visibility** → Public. Until then, pulling needs
  `docker login ghcr.io` with a token carrying `read:packages`.
- **Retention.** Every push to `main` adds a version, so untagged versions
  accumulate. Package settings has no automatic cleanup; prune them by hand
  or add a scheduled job using
  [actions/delete-package-versions](https://github.com/actions/delete-package-versions).

Storage and (for private packages) bandwidth count against the account's
Packages quota - free and generous for public packages.

## 7. Verifying that an image really came from this repo

Every published digest carries a Sigstore-signed
[SLSA build provenance attestation](https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds)
created by `publish.yml`. Nothing to enable - artifact attestations are free
on public repositories for every GitHub plan (private and internal repos need
Enterprise Cloud; drop the attest step on a private fork).

Anyone can check an image before running it:

```bash
gh attestation verify oci://ghcr.io/<owner>/<repo>:latest -R <owner>/<repo>
```

It passes only for images this repository's workflow built and signed, and
reports the commit, workflow and run that produced them. An image someone
else pushed under a look-alike name fails.

Because the workflow also pushes the attestation to GHCR beside the image,
registry-side verifiers (cosign, Kyverno and other admission controllers) can
check the same signature without calling the GitHub API. Each published
version therefore gets one extra untagged referrer entry in the package list -
that is the attestation, not junk; leave it alone when pruning.
