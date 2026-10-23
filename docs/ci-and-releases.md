# CI and releases

BlueBuild builds the two active recipes against approved Bluefin and Bluefin DX
`stable` digests committed as `image-version: stable@sha256:…`. Each profile publishes independently to `ghcr.io/closure-labs/finite`.

For human findings decisions, start with [security review](security-review.md).
[Implementation status](ci-maintainer-decisions.md#bootstrap-and-cutover) tracks
the one-time policy activation and release transition.

## Build and validate

[Build Finite](https://github.com/closure-labs/finite/actions/workflows/build.yml)
runs on pull requests, merge groups, main pushes, daily schedules and manual
dispatches. It selects work from the complete Git diff for each event. The image
work below runs in the protected merge queue and on applicable main/manual runs;
PR updates run documentation and the selected full Nix/runtime aggregate:

| Changed inputs | Required work |
| --- | --- |
| README, changelog, license or `docs/` only | Text style and local Markdown links |
| Tests, automation, devenv lock or dependency workflows | Documentation and Nix/runtime checks |
| Nix modules, Home Manager, flake lock, Nix setup or version | Documentation, Nix/runtime checks and images whose payload derivation changed |
| One recipe | Checks and that recipe's image |
| Shared system files, signing, build CI or other paths | Checks and both active images |
| Daily schedule or ordinary manual dispatch | All checks and both active images |
| Manual dispatch with `reconcile=true` | All checks and only channels that differ from approved image-input identities or base digests |

Fast checks finish before image builds start. Documentation-only pull requests
run documentation checks. The protected merge queue builds and installs the
selected OS candidates before merge, avoiding a second disposable OS build and
installation on every PR update. The required gate rejects skipped or failed
queue image jobs and still validates the complete profile selection on PRs.
Every main push also reconciles public image identities
with the approved checkout, so a newer docs push cannot hide a superseded pending
image build. The daily schedule refreshes floating DNF and
BlueBuild module inputs while retaining the approved base digests.
Missing comparison data selects full validation. Renames include both paths,
so moving an image input into documentation still triggers image builds.

Governed workflow, signing, policy and tooling updates require an eligible
submitter as well as human review. Dependabot cannot meet the configured App's
submitter requirement for those paths. Adopt the update in a PR authored by the
configured App, a Maintainer or a Super Admin; review the new PR's exact head.
Approving the original Dependabot PR or toggling auto-merge does not change its
submitter. The early read-only preflight rejects unsupported bot submissions
before expensive validation when the public App login is configured. The
authoritative App check still verifies submitter and reviewer authority.

Use hosted CI for full Nix evaluation, aggregate checks, VM qualification and
large ISO verification. Local full-check evaluation exhausted memory on the
15-GiB development workstation during the October 14 rollout. Keep local review
to small standalone tests and text checks; do not run unbounded or parallel Nix
verification alongside desktop work. Any specifically requested local heavy
run needs explicit process memory and CPU limits before it starts.

Maintenance, registry and publication commands use `lib/ci-tools.nix`, which
reads the existing `flake.lock` directly. Its shells share package definitions
with the flake's CI and release shells without evaluating the Home Manager/Den
configuration. SecretSpec mapping and trusted PR validation use the same
lightweight entry point and retain their existing credential and review checks.
The devenv check and lock-validation tasks also obtain their launchers here.
The check launcher discovers the proof names and aggregate derivation in one
root-flake evaluation, releases that evaluator, builds the aggregate, then checks
standard flake outputs and every proof closure. Creating the launcher itself
does not evaluate Den or Home Manager. The lock updater retains its exact
flake-provided devenv package and reviewed weekly update workflow.

Foundation owns the Home Manager modules, catalog and tested dependency lock.
Finite pins a published Foundation release commit and includes its source and
an offline-ready personal consumer in the image. The Foundation update workflow
opens a reviewed PR changing only its pin, lock and source provenance. It never
merges that PR automatically. Foundation's own CI validates its default profile
and role/package combinations before release; Finite validates its OS integration.

Finite still pins Den and its gen hub for repository module orchestration. These
tooling dependencies do not override Foundation's independent Home Manager pins.

Nix concurrency is measured per runner, including CPU affinity and cgroup limits.
The shared setup verifies the Determinate client and effective build/evaluation
settings after installation. A standard 4-CPU/16-GiB runner uses four build jobs,
one core per job and four evaluation threads; smaller or larger runners receive
a CPU/memory budget. The 2-CPU/4-GiB qualification guest receives one build job,
two cores per job and one evaluation thread. See the
[Nix workflow resource audit](nix-workflow-resources.md) for coverage and limits.

The shared Nix setup applies the centralized public substituters and trust keys
for both flakes and lightweight CI tools. The checks store and downloaded source
trees use platform/dependency-generation keys. Checks generations bind both lockfiles,
the tool-shell definition and SecretSpec source identity, so ordinary source commits
do not repack the store. Nix still evaluates every current check derivation.
Successful check aggregates retain a temporary GC root through post-job save.
Before a new snapshot is saved, garbage collection targets a 1 GiB store; rooted
paths can prevent reaching that target. Explicit baseline benchmarks retain the
old source-revision key and uncapped store for a faithful comparison.
Only successful trusted main checks save shared store snapshots.
Cache maintenance retains two main generations;
PR and merge-queue jobs remain readers. GitHub restores are scoped to the current
and base/default branches. The two v2 fallback snapshots remain until two distinct
bounded generations exist, then maintenance can retire them. Registry credentials
remain outside cached paths.

VM validation uses the pinned `vm-tools` output from `lib/ci-tools.nix`, with the
existing Determinate client and public binary caches. The shared setup action
provides QEMU's VM-test build, OpenSSL, Skopeo, SSH, ISO/firmware editors and
Secure Boot firmware. It preserves the host Nix and BlueBuild executables.
Firmware paths enter only through a validated Nix store output. Qualification
records the actual executable paths and hashes, package versions and firmware
hashes; legacy apt contexts remain readable and different contexts cannot reuse
qualification. Changing this tooling requires fresh VM evidence.

**Benchmark VM tool provisioning** is reusable and can run manually. Build Finite
also invokes it for the dedicated `perf/nix-vm-tools` draft branch; ordinary PRs
do not run this experiment. It compares the original apt command, apt without
recommended packages and Nix, with three cold/warm repetitions per lane. All
lanes start after the same Determinate and image-tool setup without an Actions
store restore. Reports bind the exact checkout, proposal, locks, native run and
attempt, runner image and executable/firmware identities. Complete native job
times include setup, both passes and artifact handling. The experiment excludes
the preceding Docker build; merge-queue image/VM jobs exercise that path.

The draft's adoption gate requires all nine measurements and successful image/VM
checks. Nix must beat both apt lanes on complete-job medians and improve common
setup plus cold provisioning by at least 10 percent and five seconds, on one
matching runner-image version. Missing, failed or inconsistent evidence cannot
authorize rollout. A slower or inconclusive result leaves the PR in draft.

Contract checks declare separate source inputs for home integration, Nix lifecycle,
firmware/ISO editors, dependency updates, workflow lint and repository policy.
The full `.#ci-checks` aggregate remains required. Changes outside a group's
inputs can reuse its existing Nix result; changed tests or their dependencies
change the derivation normally. Documentation jobs install only missing tools.

With `FINITE_OPTIMIZED_CACHES=true`, small jobs realize pinned closures from
public binary caches without an Actions restore; aggregate checks keep their
store snapshot. Warmed source downloads did not improve these small-job timings,
so `cache-mode: optimized` retains source restoration only for explicit
experiments. Without the switch, jobs keep the baseline full-store restore.
`FINITE_CACHIX_WRITER=true`
enables a separate successful-main writer using devenv’s built-in SecretSpec
Cachix authentication, limited to
four declared image/scanner/audit/resolver tool closures. Preparation batches
tool realization and closure validation before exposing that write credential.
Explicit `cache-publish.py prepare --include-proofs MANIFEST` also seeds bounded
check proofs. Automatic writing remains disabled pending net savings. The
[v0.8 plan](v0.8-release-plan.md) and [CI optimization review](ci-optimization-review.md)
record the experiments and adoption criteria.

Nix uses its native 15-second connection timeout, 60-second stalled-download
timeout and three download attempts. The stall timeout measures inactivity,
not total transfer duration. Verbose Nix output reports fetch and evaluation
activity during checks; test and evaluation failures remain fatal.

For Nix changes, CI evaluates `image-payload.drvPath` at the base revision and the actual checked-out
PR, merge-queue or main revision. These identities include their declared Nix
dependencies. Matching identities skip the corresponding image rebuilds;
changed identities select both active profiles. Evaluation uses the committed lock file and records both identities
in the job summary. It evaluates the dependency graph without building payloads.

The Nix comparison adds to images selected by recipe and system-file changes.
An evaluation failure selects both active images. The daily full build also
checks floating package and BlueBuild inputs outside Nix's dependency graph.

Premerge VM selection compares changed lockfiles at the base and actual assembled
checkout. A change confined to original input-reference metadata does not force
VM validation when every resolved revision, hash and graph edge is identical.
Payload dependency comparison and the full check aggregate still run. Resolved
dependency changes, boot/installer changes and unavailable or malformed lock
comparisons retain VM validation for both profiles. Unknown lock versions also
retain validation.

Hosted checks evaluate the aggregate derivation in one process, then build that
exact derivation in a separate process. This releases the Home Manager evaluation
heap before builders start. Each phase retries only recognized transport failures;
build retries reuse the evaluated derivation. The successful aggregate remains
rooted for post-job cache collection. Job summaries report evaluation and build
time separately, including retries; no lock updates are allowed during evaluation.

The required `CI gate` runs for every event. It requires success from selected
jobs and verifies that other jobs were explicitly skipped. Failures,
cancellations and missing selection outputs block merging. Merge-queue checks
use the queue's base and proposed merge revisions.

| Run | Registry permissions | Signing |
| --- | --- | --- |
| Pull request or merge group | Read | Public key available for policy assembly |
| Trusted main build | Write | Unsigned candidate only |
| Isolated main signer | Write | Environment-scoped `COSIGN_PRIVATE_KEY`, after security gate |

Both paths use the same Docker builder and BlueBuild CLI v0.9.37, installed
from the digest in `sources/bluebuild-cli.json` after signature verification.
The Nix CI shell supplies the supporting tools. Invoking the verified CLI
directly avoids duplicate cosign, SLSA verifier and CLI downloads during each
image build. Publication runs serialize. The CLI builds, caches and pushes an unsigned
`candidate-PROFILE` tag and its generated candidate aliases. Stable candidate
tags preserve per-profile layer caches; they are diagnostic outputs, not release
channels. Public channel tags change only after verification succeeds.

The builder's `default-load=true` setting makes validation images available for
inspection. The final-image step runs after the build and checks the
Nix seed, packages, profile, signing policy, kernel, matching initramfs with
LUKS/FIDO2 support, and `bootc container lint`.
Publication resolves the candidate once and verifies its immutable digest,
exact approved base digest and source revision. An independent inventory and
vulnerability scan must pass before a separate fresh job signs that digest.
Encrypted Secure Boot VM qualification follows signing. Promotion rechecks scan
evidence and the live signature, then copies that
same manifest to the profile's channel tags with `--preserve-digests`, and
confirms each destination digest. Signatures remain valid because candidate and
channel tags share the same repository and image digest. A failed verification
leaves public channels unchanged through this workflow. Registry write tokens
remain broader than tag-scoped permissions; see the documented residual risk. Tag updates are individually atomic;
reconciliation detects and repairs interrupted promotion of aliases.

Each profile's build artifact contains its image reference, labels, generated
Containerfile and publication plan. Separate artifacts record native Syft and
SPDX inventories, raw Grype results, policy decisions, qualification and promotion. The final image's base-digest label
records the actual Bluefin input. Its source revision identifies the Finite
commit that was built.

Every candidate publication requires successful boot qualification of its exact
digest, including encrypted-root fresh install, upgrade and rollback where a
predecessor exists. Fresh and upgrade scenarios run on separate runners and
aggregate their bound receipts before promotion. An optional pilot reuses
identical authenticated qualification for at most 24 hours, preserving its
original time; new digests require new tests. Missing or failed acceptance blocks
promotion. The `qualify` dispatch input bypasses reuse.
See [workstation qualification](workstation-qualification.md) for enforcement,
upstream kernel/module preservation and durable release bundles.

The active channels are `finite` and `finite-dev`. Kernel and module updates
arrive together through authenticated upstream image updates. See the
[upstream preservation contract](upstream-kernel-variants.md) for details.

## Bluefin updates and recovery

[Update Bluefin upstream](https://github.com/closure-labs/finite/actions/workflows/update-bluefin.yml)
polls GHCR every four hours at minute 43 and supports manual dispatch. It resolves
both `stable` references to immutable Linux amd64 manifests, validates their
platforms, and compares them with the committed recipe digests. For an OCI index,
it selects the unique Linux amd64 child so unrelated architecture updates do not
trigger builds. Both lookups must succeed before any recipe is changed.

Changed digests produce one `automation/update-bluefin` PR. The active profile for each
changed foundation uses the new digest. Existing change selection builds only
those profiles, and the trusted updater waits for validation before enabling
protected merge-queue integration. A successful short resolution job records the
observed digests and check time in its summary and a 14-day evidence artifact,
independently of the longer PR validation job.

A separate job reconciles all three public channel tags against the approved digests on
main, even if upstream resolution or PR validation fails. Missing tags, a wrong
base or profile, stale or missing image-input identity, and divergent
`finite`/`latest` aliases require recovery.
If a main publication is already active, recovery waits for the next poll;
otherwise it dispatches Build Finite with `reconcile=true`. That run recomputes
the affected profiles before building. Observing an upstream update never marks
it as published, so failed post-merge publication is retried on later polls.
This comparison covers approved base updates; ordinary code changes and floating
dependencies retain the daily full-build safety net.

Registry reads use four attempts at most, each bounded to 30 seconds, with 2, 4
and 8-second retry delays for transient errors. Authentication failures, invalid
metadata and exhausted retries fail explicitly. Only GHCR's `manifest unknown`
response denotes a missing public tag; a generic 404 or outage is an error.

[Bluefin upstream check freshness](https://github.com/closure-labs/finite/actions/workflows/upstream-health.yml)
runs daily at 07:11 UTC and fails if no resolution job succeeded in 24 hours.
It checks the resolution job rather than the parent workflow, so an unrelated
failed PR validation does not hide a successful poll. GitHub can delay scheduled
workflows; this monitor exposes stale checks when it runs but cannot guarantee
alerts during a platform-wide Actions outage. The daily full build remains at
08:17 UTC.

To inspect state locally without publishing or dispatching workflows:

```bash
nix develop --file lib/ci-tools.nix shell --command python3 scripts/ci/bluefin-upstream.py reconcile
```

To recover approved channels manually:

```bash
gh workflow run build.yml --ref main -f reconcile=true
```

## Image signing

`cosign.pub` is the public trust key. The matching private key belongs in the
`image-signing` environment's `COSIGN_PRIVATE_KEY` Actions secret. This
environment admits only `main`. Release-asset signing uses a separate copy in
the approval-protected `release` environment. Builders and scanners receive no
signing key; remove the repository-wide copy after migration and retirement of
older workflows. Verify a published digest from
a trusted checkout:

```bash
cosign verify --new-bundle-format=false --key cosign.pub IMAGE_REFERENCE
```

The image configures signature verification for `ghcr.io/closure-labs/finite`
with these files:

| File | Purpose |
| --- | --- |
| `/etc/pki/containers/finite.pub` | Finite public key |
| `/etc/containers/policy.json` | `sigstoreSigned` policy with `matchRepository` identity |
| `/etc/containers/registries.d/closure-labs-finite.yaml` | Enables Sigstore attachments for the repository |

When preparing an existing workstation for a new key, verify the published
image with the reviewed public key, install that key, and update the Finite
entry in the container policy and registry configuration. Preserve the
existing policies for other registries. Then use
`bootc switch --enforce-container-sigpolicy` and review the staged deployment
before rebooting.

Generate replacement key pairs in a private directory outside the source
checkout. Upload the private half with
`gh secret set COSIGN_PRIVATE_KEY --repo closure-labs/finite --env image-signing < cosign.key`
and repeat with `--env release`
and commit the public half. Validate the resulting image and host policy as
part of key rotation.

## Publish a release

Stable `VERSION` values use numeric `MAJOR.MINOR.PATCH`. Development prereleases
use `MAJOR.MINOR.PATCH-dev`, such as `0.8.2-dev`. Both use the paired preparation
and publication workflows. The retired per-channel workflows remain stable-only.
Before preparing a stable version, update `VERSION` and add its dated changelog
entry through the protected queue.

1. Update `VERSION` and add a dated entry to `CHANGELOG.md` in a PR. The version
   also identifies the staged Home Manager template.
2. Pass `CI gate` and merge through the queue. Wait for successful signed main
   builds, exact-digest qualification and promotion for the selected channels.
3. Delivery reconciliation runs **Prepare two-image release approval** after both
   images qualify at the same revision with preserved ISOs. It creates one
   immutable proposal for tags such as `finite-0.8.2` and `finite-dev-0.8.2`, or
   `finite-0.8.2-dev` and `finite-dev-0.8.2-dev` for the prerelease. Manual
   preparation accepts the successful same-revision build run.
4. Review both products, qualification evidence, scan decisions and claimed
   physical-hardware results in the proposal. Its human approval and the protected
   signing environment remain required. Merging the decision starts paired
   publication; see [Durable releases](workstation-qualification.md#durable-releases).
   Do not publish a separate `vVERSION` release before installer qualification.

After a stable pair publishes successfully, **Delivery and decision pipeline
health** opens a PR for the next patch's development version, for example
`0.8.1` → `0.8.2-dev`. It checks that both stable pages are published, include
signed-checksum assets, and resolve to the same source commit. A partial stable
release cannot start the cycle. The PR changes only `VERSION` and `CHANGELOG.md`,
adding the development notice and an initial versioned entry. It must pass the
normal queue. Once merged, both images build
and qualify before a separate paired prerelease proposal is prepared for review.

Prereleases set GitHub's `prerelease` flag and explicitly disable `make_latest`
through the [GitHub release API](https://docs.github.com/en/rest/releases/releases#create-a-release).
They retain the stable publisher's live human authority, security admission,
signatures, immutable assets and recovery journal. Publishing a prerelease does
not bump the version again. Each development version identifies one immutable
pair; subsequent development commits do not replace its tags or assets. The
hourly observer and manual health dispatch reconcile missed completion events.
The existing published `0.8.1` pair permits the initial `0.8.2-dev` preparation.
A manually reviewed version bump may skip a reserved development version, such
as `0.8.2-dev` → `0.8.3-dev`. Preparation requires the latest earlier stable patch
in the same major/minor series to have a complete published pair. It discovers
at most 1,000 release records and fails closed on incomplete inventories. A
newer partial, reserved-tag or visible draft stable pair blocks preparation instead of falling back
to an older pair. A skipped prerelease never supplies the stable baseline, and
its payload, tags, assets and version reservation retain their original identity.

The channel tags continue to receive daily builds. Release records identify
specific source revisions and image digests for reproducibility.

## Maintain dependencies and repository policy

Nix lock updates, coordinated Home Manager/Nixpkgs release updates and the
Determinate checksum update use the retained dependency workflows. Their
protected-branch automation reads the repository-available GitHub secret
`MERGE_QUEUE_PAT` (including an organization secret granted to this repository).
Workflows map it to SecretSpec's internal `MERGE_QUEUE_TOKEN` key, so existing
local pass entries keep their names. Release publishing uses the same mapping.

The checked-in policy at `automation/github/repository-security.json` describes
the action allowlist, SHA pinning, default read-only token and repository
security settings, complete environment protections and effective main-branch
rules. Missing API access fails the audit; excluded controls are explicit in the
JSON output. Audit the live repository from a checkout with GitHub CLI
access:

```bash
nix shell --file lib/ci-tools.nix ci-repository-security-audit --command finite-repository-security-audit
```

The daily/manual **Audit repository security policy** workflow runs this same
read-only audit. Configure the GitHub App client ID as the Actions variable
`SECAUDIT_CLIENTID` and its PEM private key as the Actions secret `SECAUDIT_PEM`.
The App needs repository Administration: read and automatic Metadata: read access
and must be installed on Finite. The same App can serve other repositories;
each audit requests a short-lived token scoped only to its current repository
and Administration: read. The token is revoked when the job finishes.
Organization-level variables/secrets also work when their repository access
includes Finite. Missing credentials or inaccessible settings fail visibly.
Review the retained JSON result and rotate the App private key periodically.

## Hosted diagnostic checks

All six benchmark workflows run on demand. Use them for a specific diagnostic
or a measured comparison, with the tested inputs and results recorded. Daily
production builds and published-image audits provide the regular coverage.

The **Benchmark image tool setup** workflow can run at a review branch with
`validation=cache-lanes`. The same entry
point accepts `validation=qualification` with exact signed candidate/predecessor
digests, matching profile/channel, build identity and source revision. This
diagnostic mode runs fresh Secure Boot installation, upgrade/rollback and desktop
checks using the branch's installer/test code. It never promotes a channel, uses
distinct diagnostic artifacts, and cannot supply production qualification evidence.
ISO construction still creates unique installation tags in the existing registry.

## SecretSpec and local tasks

`secretspec.toml` declares credentials, signing keys, six CI pilot switches and the
`FINITE_QUALIFIED_ISO_CHANNELS` selector. The selector defaults to `finite`;
use comma-separated supported channel names or `all` for a broader rollout.
Preservation, predecessor ISO reuse, strict release fallback and pruning apply
only to selected channels while the preservation switch is enabled.
GitHub Actions supplies backend values through the `github-actions` environment
provider; signing and authority tasks use the encrypted `local = "pass://"`
provider locally. Cachix uses devenv’s built-in SecretSpec requirement with
the system keyring, independently of those task profiles.
The same explicit profile/scope names identify image signing,
release signing, release publishing, repository reads, audit App credentials and
trusted updates.
GitHub scheduling guards still use repository variables before a job exists;
runtime switches are resolved and validated by SecretSpec before use.

Production repository overrides enabled inventory and whole-qualification reuse
on October 15, 2026 after the two active variants passed hosted measurements.
Local/source defaults remain false; automatic Cachix writing and DB transport
remain off. See the [measurements, activation receipt and rollback commands](new-os-reuse-results.md#production-activation).

The pinned SecretSpec 0.19.1 CLI supports standalone profiles and scope filtering.
Its checksum-pinned release package avoids compiling all of devenv just to resolve
CI credentials. Tool realization happens before supplying signing/write keys.
Signing keys reach only signer commands; the audit App key is cleared after token
generation. Secret values never enter Nix evaluation, cached paths or artifacts.
The default developer profile contains public options only. The available devenv
CLI resolves Cachix internally for private pulls and explicit uploads;
`CACHIX_AUTH_TOKEN` has no declaration in `secretspec.toml` and is never exported
into the developer shell. No separate Cachix client installation is required.
The recommended setup in `devenv.yaml` is:

```yaml
secretspec:
  enable: true
  profile: default
  provider: keyring
  cachix_auth_token: true
```

Run `devenv shell` interactively once to enter the Cachix token and
save it in the system keyring:

```bash
devenv shell
```

Noninteractive commands, including direnv and
cache tasks, cannot prompt. Existing pass entries are not migrated or deleted;
enter the token in the new keyring prompt before using those commands. For a
backend policy requiring a different secret name, replace `true` with that name.
See the [devenv Cachix setup](https://devenv.sh/binary-caching/).

`ci:cache:check` realizes and validates bounded check proofs without credentials,
then starts a separate minimal devenv environment containing only those roots.
Devenv manages the uploader and token. The trusted main writer uses the same
mechanism for its allowlisted tools. GitHub supplies the existing repository
secret `CACHIX_AUTH_TOKEN` only to that upload step as `FINITE_CACHIX_TOKEN`;
the temporary environment selects SecretSpec’s `env` provider and that custom
secret name. It has no signing manifest or developer tasks. Public cache readers
continue to use the Nix setup action without a write token or devenv bootstrap.
Workflows use no Cachix actions or Cachix-hosted runner labels; devenv owns
uploads. The GitHub Nix store snapshot action remains separate from Cachix.
GitHub's secret API returns metadata rather than token values, so a local shell
cannot retrieve the repository secret. Store the local token in the keyring;
Actions supplies the repository secret only to the trusted upload step.
The uploader verifies every remote closure hash after devenv exits, including
when devenv reports an uploader warning without failing its command.

Cachix uses an installed devenv CLI when available; runners without it realize
`.#devenv`. The input follows upstream without a fixed release tag, and the CLI
need not match the module lock's version. The existing weekly **Update Nix flake
inputs** workflow refreshes both `flake.lock` and `devenv.lock` and opens a PR.
Runners adopt those updates after merge; Dependabot is not needed for this path.
The lock updater disables SecretSpec in an isolated temporary configuration and
clears write credentials while refreshing public inputs. The developer
configuration keeps its keyring requirement.

The standalone `release-publishing` scope resolves the trusted repository token
into `GH_TOKEN` only for the controlled tag/draft child. It needs repository
contents write and workflows write for a frozen source whose workflow files
differ from current main. Signing keys and the original token variable are
absent from that child. Local use resolves the same profile through pass; it
never resolves during ordinary shell startup. A separate hosted recovery
workflow can authenticate a completed unsigned packet and preserve its original
source/provenance after a signer or publisher failure. It retains the protected
release environment and refuses existing tags or releases. See the
[v0.8 recovery sequence](v0.8-release-plan.md#frozen-source-draft-recovery).

Populate a task-specific pass entry interactively, then run its task:

```bash
secretspec set GH_TOKEN --profile repository-read --provider pass
secretspec set COSIGN_PRIVATE_KEY --profile image-signing --provider pass
secretspec set MERGE_QUEUE_TOKEN --profile updater --provider pass
secretspec set MERGE_QUEUE_TOKEN --profile release-publishing --provider pass

devenv tasks run ci:cache:options
devenv tasks run ci:cache:writer:prepare
devenv tasks run ci:cache:check
devenv tasks run repository:audit
```

Pass entries use `secretspec/finite/PROFILE/KEY`. `FINITE_SECRETS_PROVIDER=pass`
selects pass explicitly for local scoped wrappers; the default `local` alias
uses the same backend. Existing global file-provider settings are overridden
by these explicit task selections. Do not put private values in this manifest.
`image:verify`, `image:sign` and `release:sign` are explicit developer tasks;
image tasks require an immutable `IMAGE_REFERENCE`. They do not execute as
part of ordinary CI checks or developer shell initialization.

The [October 15 reuse results](new-os-reuse-results.md#production-activation)
record active reuse settings and rollback commands. Earlier cache experiments
are indexed under [reports](reports.md#releases-and-measurements).

## Update reliability and measurement

Source lookups use at most four GET attempts, with a 30-second attempt timeout,
10-second socket timeout and 150-second total retry budget. Retry delays start
at 2, 4 and 8 seconds; a larger `Retry-After` is honored only if it fits within
the budget. Authentication, permission and malformed-release errors fail without
retrying. Missing future branches or HTTP 404 mirrors report no change; outages
fail the update. Existing Determinate pins are replaced only after complete,
nonempty asset downloads and metadata validation.

Lock generation preserves file content and appends a missing final newline
before computing change outputs. Generated updates pass text checks before a
PR is created. Dedicated credentials remain scoped to existing PR/merge steps;
the default workflow token has contents-read permission.

Updater jobs allow 270 minutes, including a bounded 240-minute wait for child
validation. Existing PR and manual runs are reused only for the same branch
and commit. Failures include a direct run link and never enable auto-merge.
A fresh dispatch after integration uses the corrected workflow; rerunning an
older run uses its older revision.

The merge queue also allows 240 minutes for required checks. This exceeds the
220-minute configured validation path and leaves allowance for queueing. A
delivery-policy contract checks these budgets together; raising a child job's
limit requires reviewing its orchestration deadlines.

The [CI optimization review](ci-optimization-review.md) records the 30-day
baseline, confirmed causes, current bottlenecks and ranked follow-up work.


## Image vulnerability gate

Native Syft inventory and Grype results bind each scan to an immutable image
and profile. The checked policy requires a substantial RPM inventory, verified
Fedora release identity, current Fedora/KEV coverage and a healthy scanner.
Databases and feeds must be at most 48 hours old; publication evidence must be
at most 24 hours old. Signing and promotion verify current evidence again.

In `maintainer-decision` mode, publication also requires authenticated human
acceptance of the findings. New or worsened risk opens a decision PR for a
Super Admin; covered findings continue unattended. The
[security review guide](security-review.md) explains approval, and the
[rollout status](ci-maintainer-decisions.md#bootstrap-and-cutover) identifies the
activation boundary. Technical verification failures stop publication.

**Audit published image security** rescans both active channels daily and can
run manually. CL Decider monitors audit health and maintains a recovery issue.
Release preparation also collects fresh scan evidence for its exact digest.

Bluefin base updates and candidate builds verify immutable base digests using
`sources/bluefin.pub` and its reviewed fingerprint policy. Publisher key rotation
requires review of both files. Cosign signatures bind the exact image used by
bootc's container-signature policy. Full SPDX inventories are retained as OCI
referrers, with their hash and size bound in the signed
[SBOM reference](automation/sbom-reference-v1.md).


## Main advancing during publication

Promotion retains the exact qualified revision and digest. A newer main revision
is acceptable only when GitHub proves it descends from that revision and the
complete comparison changes only `README.md`, `CHANGELOG.md`, `.great_cto/tasks.md`
or files under `docs/`. Renames check both paths; incomplete comparisons, unknown
file statuses, divergent history and API failures cannot authorize promotion.
The main reference is checked again after the comparison, and the public channel
must still match the predecessor recorded before qualification.

Image, signing, policy, workflow and VM harness changes still require qualification
at the new revision. Sequence those merges after active publication finishes to
avoid discarding completed work. In particular, a successful diagnostic run does
not replace the production qualification record.

## Delivery resilience and release readiness

Changes to boot configuration, systemd units, SELinux, the installer and the VM
harness select merge-queue VM validation for both images. The required CI gate
checks that both profiles ran on the assembled queue revision. PR updates run the
full selected Nix/runtime aggregate and governed-tree preflight. Each queue image job exports its assembled candidate as
an OCI archive and supplies that archive to the pinned installer. It boots the
candidate with Secure Boot, encrypted storage and enforcing SELinux, then checks
Nix startup and Home Manager initialization. This fresh-install validation fits
inside the existing 120-minute image-job budget; production upgrade and rollback
qualification still run before promotion.
The image export, installer preparation, ISO build and acceptance invocation
record separate stage timings. These reports are discovery evidence and grant
no approval authority. See the [workflow architecture audit](ci-architecture-2026-10-23.md)
for the measured duplication and the remaining experiments.

Premerge runners have no signing keys or registry write token. Their installer
uses a disposable unsigned local reference, and their receipts identify
`local-image` with `validationOnly: true`. Production qualification requires its
existing signed GHCR digest and trusted main context. Local receipts cannot
supply publication or release evidence. Raw VM disks and credentials stay in
private temporary directories; retained logs pass through the existing redactor.

The GDM SELinux fixture accepts an absent state directory or a DynamicUser
symlink. It creates its mount target inside a private overlay of `/var/lib`,
removes only the overlay copy of a symlink, and binds disposable fixture data.
Native policy data remains visible. It checks recursive relabeling, preserved
ownership and modes, migration, and repeatability without changing real GDM
state. Unexpected file types fail with a named diagnostic.

**Delivery and decision pipeline health** runs hourly and after trusted main build and release
workflows. Its publisher monitor is read-only. Separate reconciliation jobs
retain automatic preparation and audit/decision issue reporting, even when
publisher health fails. Its summary links the latest recorded qualification and promotion for
each channel, reports failing jobs, and flags promotions at least 36 hours old.
Publisher identity artifacts bind each execution to its merged proposal, payload,
version and native run attempt before preparation transfers. Health verifies the
native artifact binding, SHA-256 and bounded JSON before reporting queued,
running, environment approval wait, failed, partial or published states. Missing
or uncorrelated legacy metadata reports unknown with inspection guidance. Failed,
partial and missing publishers make health fail even when builds succeeded;
native environment approval waits are informational blockers. These observations
never authorize approval or publication. See [publication recovery](release-set-controller.md#upload-and-publication-recovery).

For a new stable `VERSION` such as `0.8.2`, trusted main builds select both
images and force fresh qualification. After both profiles succeed and preserve
their qualified ISOs at that revision, delivery reconciliation dispatches
**Prepare two-image release approval**. Preparation checks readiness before
installing tools or downloading products. A development version such as
`0.8.2-dev` follows the same path only after its latest earlier stable pair succeeds.
Unsupported version formats skip with an explanation. Existing paired releases, open bot release
proposals and recorded release decisions prevent repeated preparation. Drafts,
partial releases and existing tags require recovery of the approved products.
The same version cannot silently replace tags or assets.

A failed or cancelled paired preparation stops automatic dispatches for that
source revision. Delivery health records the failure instead of repeatedly
downloading both ISOs. Inspect the failed preparation, correct its cause, and
explicitly dispatch **Prepare two-image release approval** with the successful
same-revision build run. A new main revision can prepare automatically again.
Paired preparation can reuse authenticated inventory bytes from trusted main
builds; vulnerability databases, findings and policy results are scanned anew.

Human review of the paired proposal and the protected release signing environment
remain required. Merging the proposal starts **Publish approved two-image
release**. Its existing journal, immutable packet, fresh admission checks and
partial-publication recovery remain in force. The per-channel release and
recovery workflows are labelled **Retired**; use the paired workflows instead.
Manual paired preparation accepts a successful same-revision build run. Manual
publication/recovery accepts the approved proposal hash and, when needed, its
immutable signed recovery packet.

GitHub authority, controller, release-journal and health metadata reads allow
three attempts with 30-second attempt limits and a 100-second total budget.
Timeouts, connection failures, HTTP 408/429 and transient server failures retry.
HTTP 403 retries only with explicit rate-limit evidence; ordinary permission
failures, invalid JSON and oversized responses stop immediately. Retry-After
and rate-limit reset delays must fit the remaining budget. Diagnostics include
the endpoint path, HTTP status, request ID and attempt, without response bodies
or credentials. Mutations are never blindly retried; subsequent reconciliation
checks remote state before another operation.

Health completion triggers exclude PR and merge-queue validation runs. Same-repository
main push, scheduled and manual delivery completions remain observed even when
they fail. Hourly and explicit health dispatches retain missed-event recovery.

The read-only **Observe workflow costs** workflow retains native run/attempt,
source, job/profile and phase timings, including failed/cancelled work. It runs
weekly or manually with an optional UTC rollout timestamp for a 14-day baseline
and seven-day observation. Reports convey no approval authority and unavailable
cache/retry/runner detail remains unknown. See the
[October 23 audit](ci-workflow-audit-2026-10-23.md) for findings, candidate recovery
constraints, native links and the remaining measurement gates.
