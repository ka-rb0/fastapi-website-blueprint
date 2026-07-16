# GitHub repository setup (one-time)

The files in the repo configure CI and Dependabot automatically, but a few
protections live in GitHub's **settings** and must be enabled once by hand.

Everything below is **free for public repositories**. Items marked 💰 cost
money on private repos (they need paid GitHub Advanced Security) - if you
clone/fork this template and make your copy **private**, skip or disable
those items as noted, otherwise the affected CI jobs will fail.

## 1. Import the branch ruleset

**Settings → Rules → Rulesets → New ruleset → Import a ruleset** and pick
[.github/rulesets/protect-main.json](../.github/rulesets/protect-main.json).

What it enforces on `main`:

- no deletion, no force-push
- changes arrive via pull request (0 required approvals - solo-maintainer friendly)
- the `lint` and `test` checks must pass, and the branch must be up to date
  with `main` when it merges.

Note: with the ruleset active, GitHub rejects direct pushes to `main` - open
a PR instead. The [pre-push hook](../.githooks/pre-push) stays useful as a
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
  blocks PRs that introduce vulnerable dependencies. On a private fork,
  delete the job.

The other CI audits (`pip-audit`, `npm audit`, `zizmor`) query public
advisory databases and are free everywhere - keep them.
