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

## 6. Container images - nothing to click, three things to know

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

The third thing needs no setting, only a warning, because GitHub's own UI
gets it wrong:

- **Do not pull the `sha256-…` tag.** The package page lists it under
  "Recent tagged image versions" and - worse - its **Install from the command
  line** box offers it as a ready-made `docker pull` command. That tag is not
  an image. It is where the OCI referrers spec parks this version's signed
  attestations (section 7), and pulling it fails with
  `unsupported media type application/vnd.oci.empty.v1+json`. GitHub shows it
  because the snippet names the most recently published version, and the
  attestations are always pushed after the image they describe. Pull `latest`,
  a version tag, `main`, or the digest with `@sha256:` - note the `@` and the
  colon, which is what distinguishes a real digest reference from this tag.

Storage and (for private packages) bandwidth count against the account's
Packages quota - free and generous for public packages.

## 7. Verifying that an image really came from this repo

A digest proves an image arrived intact. It proves nothing about where it came
from - anyone can build anything and push it under a similar name. Attestations
close that gap: they are signed statements _about_ a digest.

Every digest `publish.yml` publishes carries two, both signed:

- a [SLSA build provenance attestation](https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations/using-artifact-attestations-to-establish-provenance-for-builds) -
  which repository, workflow, commit and run produced it
- an **SPDX SBOM** - the inventory of what is inside it: the Debian packages
  from the base image and the Python distributions from `uv.lock`. This is what
  answers "are we affected?" the day a widely-exploited CVE is announced,
  without rebuilding or guessing.

The signing uses no key you have to store or rotate. The workflow trades its
GitHub OIDC identity for a Sigstore certificate valid for about ten minutes,
signs with that, records the signature in the public **Rekor** transparency
log, and the certificate then expires. That is why `id-token: write` appears in
the workflow's permissions.

Nothing to enable - artifact attestations are free on public repositories for
every GitHub plan (private and internal repos need Enterprise Cloud; drop the
attest steps on a private fork).

Anyone can check an image before running it:

```bash
gh attestation verify oci://ghcr.io/<owner>/<repo>:latest -R <owner>/<repo>
```

It passes only for images this repository's workflow built and signed, and
reports the commit, workflow and run that produced them. An image someone
else pushed under a look-alike name fails. Add `--predicate-type` to check a
specific one of the two; the SBOM itself is the `predicate` of its statement,
so this prints the package inventory:

```bash
gh attestation verify oci://ghcr.io/<owner>/<repo>:latest -R <owner>/<repo> \
  --predicate-type https://spdx.dev/Document --format json \
  | jq '.[0].verificationResult.statement.predicate'
```

`publish.yml` does not just produce these and hope. Its `verify` job pulls the
published digest back out of the registry, runs both verifications, boots the
container and probes `/readyz` - so a push that publishes an unbootable or
unverifiable image goes red here instead of in a deployment.

Because the workflow also pushes both attestations to GHCR beside the image,
registry-side verifiers (cosign, Kyverno and other admission controllers) can
check the same signatures without calling the GitHub API. Each published
version therefore gets one extra untagged referrer entry in the package list -
both attestations share it - that is the signatures, not junk; leave it alone
when pruning, and do not try to `docker pull` it (section 6).

## 8. Repository security posture - OpenSSF Scorecard

The workflows above audit dependencies, code and artifacts. None of them
notice if the repository's _own practices_ slip - a disabled ruleset, a new
workflow with a floating action tag, an over-permissioned token.

[scorecard.yml](../.github/workflows/scorecard.yml) fills that gap. The
[OpenSSF Scorecard](https://github.com/ossf/scorecard) grades this repo weekly
against ~18 supply-chain checks and files the results as code scanning alerts
next to CodeQL's. Nothing to click; it runs from the checked-in workflow.

Three things worth knowing:

- **Results are public.** `publish_results: true` sends the score to the
  OpenSSF API, which backs the score badge and the data
  [deps.dev](https://deps.dev) shows. Correct for a public template; think
  before enabling it elsewhere.
- **`Branch-Protection` scores low on purpose.** That check cannot read
  ruleset details with the default `GITHUB_TOKEN`. Fixing it means storing a
  classic PAT with `repo` scope as a secret, and a long-lived broadly-scoped
  token is a worse trade than one imprecise check. The workflow comment shows
  how to opt in if you disagree.
- **`Fuzzing` scores zero on purpose**, and its alert is dismissed as
  _risk accepted_ rather than fixed. The check credits OSS-Fuzz,
  ClusterFuzzLite or OneFuzz; OSS-Fuzz only takes projects critical to global
  infrastructure, and ClusterFuzzLite would add a Dockerfile, a build script,
  fuzz targets and a corpus to a repo whose point is that you can read it end
  to end. It would also find little: every byte a client controls is framed by
  uvicorn and parsed by Starlette or Pydantic, and the only two first-party
  parsers - the `Content-Length` reader in
  [middleware.py](../src/app/middleware.py) and the request-ID guard in
  [observability.py](../src/app/observability.py) - are short total functions
  over bounded input, in a language where the failure mode is an uncaught
  exception rather than memory corruption. What a fuzzer would have been for
  is bought instead with Hypothesis, inside the normal suite: see the property
  tests at [test_body_size_limit.py](../tests/test_body_size_limit.py)
  and [test_request_id.py](../tests/test_request_id.py). Scorecard does not
  credit Hypothesis, so this closes the risk without moving the score -
  deliberately, because the score is not the thing worth optimizing.

💰 Public repos only, on two counts: publishing results requires a public repo,
and the SARIF upload needs code scanning. Delete the workflow on a private fork.

## 9. Deploying releases to Azure Container Apps

[deploy-azure.yml](../.github/workflows/deploy-azure.yml) rolls every full
release out to Azure automatically: push `v1.2.3`, and once the image is
published, signed and verified, that exact digest becomes the running revision.
Prereleases (`v1.2.3-rc.1`) publish an image and stop there, like `:latest`.

It signs in with OIDC, so **there is no Azure secret in this repo** - the three
`AZURE_*` values are identifiers, not credentials, and nothing needs rotating.

### Where the release goes: `DEPLOY_TO`

The rollout lives in its own file, but it has no trigger of its own -
[publish.yml](../.github/workflows/publish.yml) calls it, and only after its
`verify` job has proved the digest. That is what keeps the deploy tied to the
artifact that was actually verified, instead of re-resolving a tag and racing
the run that published it.

Which provider gets called is decided by the `targets` job at the bottom of
publish.yml, from a `DEPLOY_TO` **repository variable** (same place as the
`AZURE_*` variables below). It is matched case-insensitively:

| `DEPLOY_TO`                    | What happens                                                    |
| ------------------------------ | --------------------------------------------------------------- |
| `azure`                        | The release is deployed to Azure Container Apps.                |
| `all`                          | The release is deployed to every provider - today, Azure.       |
| `none`                         | The release is published but not deployed. The run is green.    |
| anything else, including unset | The run **fails** after publishing, naming the accepted values. |

Two deliberate choices there. Unset fails rather than defaulting, so a release
never quietly goes nowhere - `none` is how you say that on purpose. And the
check runs at the _end_ of the chain, so a misconfigured variable still leaves
a published, signed, verified image in `ghcr.io`; only the rollout is lost.

Scope `DEPLOY_TO` to the **repository**, not to the `production` environment:
the `targets` job deliberately has no `environment:` (an environment there
would make required reviewers gate the variable check), so an
environment-scoped value would read as empty and fail.

Adding a provider - say AWS - is three edits and no rewrite of what works: a
`deploy-aws.yml` alongside this one, one more calling job in publish.yml, and
`aws` appended to the `providers` list in the `targets` job, which is what the
accepted values and the error message are both derived from.

### The environment is what makes the login work

The job declares `environment: production`, and that is load-bearing rather
than cosmetic. An Azure federated identity credential matches **one fixed
subject**. A deploy job running on a tag would present

```text
repo:<owner>/<repo>:ref:refs/tags/v1.2.3
```

which is a different string for every release and can therefore never match a
stored subject. Naming the environment changes it to a constant:

```text
repo:<owner>/<repo>:environment:production
```

So two things must line up, once:

1. **GitHub** - **Settings → Environments → New environment**, named exactly
   `production`. Add required reviewers here if you want releases to pause for
   approval; the job waits for them before touching Azure.
2. **Azure** - the federated credential on the app registration must use
   **Entity type: Environment** with the value `production`. If it was created
   against a branch or tag instead, edit it - a mismatch fails at `azure/login`
   with `AADSTS700213`.

### What the deploy owns, and what it does not

The job reads the container app's ingress and refuses to deploy into a shape
that would fail quietly: no ingress, a `targetPort` other than 8000 (the port
the image listens on), or multiple-revision mode, where a new revision is
created with no traffic and the deploy would be a green no-op. Each of those
fails with the `az` command that fixes it.

It then sets two environment variables on every deploy, because the image
cannot get either right on its own:

- `WEBSITE_TRUSTED_HOSTS` - derived from the ingress FQDN **plus any bound
  custom domains**, so adding a domain does not take the site down on the next
  release. Unset, every route except the probes answers 400.
- `UVICORN_FORWARDED_ALLOW_IPS=*` - Container Apps puts an Envoy ingress in
  front of the container, and it is never loopback, so the image's `127.0.0.1`
  default can never match it. [QUICKSTART.md](QUICKSTART.md) argues against
  `*`, and that argument is right whenever clients can reach the container
  directly - here they cannot, because Container Apps routes to the target
  port only through ingress. Revisit this if that ever stops being true.

Everything else on the container app is left alone (`--set-env-vars` upserts
only the names it is given), so scaling rules, secrets and any other variables
you set stay yours. Note that `WEBSITE_ENABLE_DOCS` is deliberately not set:
Swagger UI stays off in production.

### It is not done until the site answers

After the revision reports `Running`, the job probes both `/readyz` **and**
the homepage. The probe alone would prove nothing about configuration -
it is exempt from the Host allowlist, so it returns 200 even when
`WEBSITE_TRUSTED_HOSTS` is wrong and every real page returns 400. That is the
most likely way this deployment breaks, and the homepage probe is what catches
it.

### Setting the target

Which resources a release lands on is a property of the repository, not of the
code, so the job reads **variables** rather than hard-coded names. Add them
under **Settings → Secrets and variables → Actions → Variables**:

| Variable               | Example                        |
| ---------------------- | ------------------------------ |
| `DEPLOY_TO`            | `azure`                        |
| `AZURE_RESOURCE_GROUP` | `fastapi-website-blueprint-rc` |
| `AZURE_CONTAINER_APP`  | `fastapi-website-blueprint-ca` |

They are variables, not secrets: resource names are not confidential, and
`vars` stay readable in the run log - exactly what you want to see when a
deploy lands somewhere unexpected. Scope the two `AZURE_*` ones to the
repository, or to the `production` environment if you later add a second
environment with its own resources; `vars` resolves either. `DEPLOY_TO` must
be repository-scoped, for the reason given above.

A missing variable or secret interpolates to an empty string instead of
failing, so the deploy job's first step checks all five - the two variables
above plus the three `AZURE_*` secrets - and names every one that is unset.
Retargeting a fork therefore needs no commit, only settings.

💰 Azure resources cost money regardless of repository visibility; the GitHub
side is free. The container app pulls from `ghcr.io`, so the package must stay
**public** (section 6) - otherwise give the container app a registry credential
with `az containerapp registry set`.
