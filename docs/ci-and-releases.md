# CI and releases

BlueBuild builds the four recipes against approved Bluefin and Bluefin DX
`stable` digests committed as `image-version: stable@sha256:…`. Each profile publishes independently to `ghcr.io/closure-labs/finite`.

## Build and validate

[Build Finite](https://github.com/closure-labs/finite/actions/workflows/build.yml)
runs on pull requests, merge groups, main pushes, daily schedules and manual
dispatches. It selects work from the complete Git diff for each event:

| Changed inputs | Required work |
| --- | --- |
| README, changelog, license or `docs/` only | Text style and local Markdown links |
| Tests, automation, devenv lock or dependency workflows | Documentation and Nix/runtime checks |
| Nix modules, Home Manager, flake lock, Nix setup or version | Documentation, Nix/runtime checks and images whose payload derivation changed |
| One recipe | Checks and that recipe's image |
| Shared next-kernel recipe or kernel script | Checks and both next-kernel images |
| Shared system files, signing, build CI or other paths | Checks and all four images |
| Daily schedule or ordinary manual dispatch | All checks and all four images |
| Manual dispatch with `reconcile=true` | All checks and only channels that differ from approved image-input identities or base digests |

Fast checks finish before image builds start. Documentation-only pull requests
run documentation checks. Every main push also reconciles public image identities
with the approved checkout, so a newer docs push cannot hide a superseded pending
image build. The daily schedule refreshes floating DNF and
BlueBuild module inputs while retaining the approved base digests.
Missing comparison data selects full validation. Renames include both paths,
so moving an image input into documentation still triggers image builds.

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

Den receives an explicit `gen` hub input, pinned to the revision tested by Den,
in both the repository and standalone Home Manager flakes. The hub's `follows`
relationships share one revision per library and avoid recursive standalone
fetches. Den is also pinned to the compatible revision; update Den and the hub
together and evaluate the refreshed locks before merging. The September 28,
2026 weekly refresh advanced Den beyond the pinned schema API and failed with
`mkSchemaOption` rejecting `specialArgs`.

Nix concurrency is measured per runner, including CPU affinity and cgroup limits.
The shared setup verifies the Determinate client and effective build/evaluation
settings after installation. A standard 4-CPU/16-GiB runner uses four build jobs,
one core per job and four evaluation threads; smaller or larger runners receive
a CPU/memory budget. The 2-CPU/4-GiB qualification guest receives one build job,
two cores per job and one evaluation thread. See the
[Nix workflow resource audit](nix-workflow-resources.md) for coverage and limits.

The shared Nix setup applies the centralized public substituters and trust keys
for both flakes and lightweight CI tools. The checks store and downloaded source
trees use platform/lock/source-revision keys. Only successful trusted main checks
save shared store snapshots. Cache maintenance retains two main generations;
PR and merge-queue jobs remain readers. GitHub restores are scoped to the current
and base/default branches. Registry credentials remain outside cached paths.

With `FINITE_OPTIMIZED_CACHES=true`, small jobs realize pinned closures from
public binary caches without an Actions restore; aggregate checks keep their
store snapshot. Warmed source downloads did not improve these small-job timings,
so `cache-mode: optimized` retains source restoration only for explicit
experiments. Without the switch, jobs keep the baseline full-store restore.
`FINITE_CACHIX_WRITER=true`
enables a separate successful-main writer with `CACHIX_AUTH_TOKEN`, limited to
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

For Nix changes, CI evaluates `image-payload.drvPath` and
`image-payload-next.drvPath` at the base revision and the actual checked-out
PR, merge-queue or main revision. These identities include their declared Nix
dependencies. Matching identities skip the corresponding image rebuilds;
changed identities select the two generic or two next
profiles. Evaluation uses the committed lock file and records both identities
in the job summary. It evaluates the dependency graph without building payloads.

The Nix comparison adds to images selected by recipe and system-file changes.
An evaluation failure selects all four images. The daily full build also
checks floating package and BlueBuild inputs outside Nix's dependency graph.

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
signed kernel maintenance and durable release bundles.

## Bluefin updates and recovery

[Update Bluefin upstream](https://github.com/closure-labs/finite/actions/workflows/update-bluefin.yml)
polls GHCR every four hours at minute 43 and supports manual dispatch. It resolves
both `stable` references to immutable Linux amd64 manifests, validates their
platforms, and compares them with the committed recipe digests. For an OCI index,
it selects the unique Linux amd64 child so unrelated architecture updates do not
trigger builds. Both lookups must succeed before any recipe is changed.

Changed digests produce one `automation/update-bluefin` PR. Both profiles for each
changed foundation use the same new digest. Existing change selection builds only
those profiles, and the trusted updater waits for validation before enabling
protected merge-queue integration. A successful short resolution job records the
observed digests and check time in its summary and a 14-day evidence artifact,
independently of the longer PR validation job.

A separate job reconciles all five public tags against the approved digests on
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
nix develop --accept-flake-config --command python3 scripts/ci/bluefin-upstream.py reconcile
```

To recover approved channels manually:

```bash
nix develop --accept-flake-config --command gh workflow run build.yml --ref main -f reconcile=true
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

1. Update `VERSION` and add a dated entry to `CHANGELOG.md` in a PR. The version
   also identifies the staged Home Manager template.
2. Pass `CI gate` and merge through the queue. Wait for successful signed main
   builds, exact-digest qualification and promotion for the selected channels.
3. Follow [Durable releases](workstation-qualification.md#durable-releases):
   run **Prepare qualified release** with the successful same-revision build run
   and a new `finite-CHANNEL-VERSION` tag. When the ISO-preservation pilot is
   enabled, leave `iso_run` empty to select the original qualified ISO. During
   the disabled pilot, supply the successful standalone ISO run explicitly.
4. Review the draft's signed assets, qualification evidence, scan exceptions and
   claimed physical-hardware results before publishing. The qualified-draft
   workflow is the canonical release path; do not publish a separate `vVERSION`
   release before installer qualification.

The channel tags continue to receive daily builds. Release records identify
specific source revisions and image digests for reproducibility.

## Maintain dependencies and repository policy

Nix lock updates, coordinated Home Manager/Nixpkgs release updates and the
Determinate checksum update use the retained dependency workflows. Their
protected-branch automation uses `MERGE_QUEUE_TOKEN`.

The checked-in policy at `automation/github/repository-security.json` describes
the action allowlist, SHA pinning, default read-only token and repository
security settings, complete environment protections and effective main-branch
rules. Missing API access fails the audit; excluded controls are explicit in the
JSON output. Audit the live repository from a checkout with GitHub CLI
access:

```bash
nix run --accept-flake-config .#repository-security-audit
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

Before these workflows reach main, the registered **Benchmark image tool setup**
workflow can run at a review branch with `validation=cache-lanes`. The same entry
point accepts `validation=qualification` with exact signed candidate/predecessor
digests, matching profile/channel, build identity and source revision. This
diagnostic mode runs fresh Secure Boot installation, upgrade/rollback and desktop
checks using the branch's installer/test code. It never promotes a channel, uses
distinct diagnostic artifacts, and cannot supply production qualification evidence.
ISO construction still creates unique installation tags in the existing registry.

## SecretSpec and local tasks

`secretspec.toml` declares credentials, signing keys, six CI pilot switches and the
`FINITE_QUALIFIED_ISO_CHANNELS` selector. The selector defaults to `finite-next`;
use comma-separated supported channel names or `all` for a broader rollout.
Preservation, predecessor ISO reuse, strict release fallback and pruning apply
only to selected channels while the preservation switch is enabled.
GitHub Actions supplies backend values through the `github-actions` environment
provider; local devenv tasks use the encrypted `local = "pass://"` provider.
The same explicit profile/scope names identify cache writing, image signing,
release signing, release publishing, repository reads, audit App credentials and
trusted updates.
GitHub scheduling guards still use repository variables before a job exists;
runtime switches are resolved and validated by SecretSpec before use.

The pinned SecretSpec 0.19.1 CLI supports standalone profiles and scope filtering.
Its checksum-pinned release package avoids compiling all of devenv just to resolve
CI credentials. Tool realization happens before supplying signing/write keys.
Signing keys reach only signer commands; the audit App key is cleared after token
generation. Secret values never enter Nix evaluation, cached paths or artifacts.
The default developer profile contains options and an optional Cachix credential.

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
secretspec set CACHIX_AUTH_TOKEN --profile local-cache --provider pass
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

Use the [measured rollout sequence](ci-rollout.md) to seed source caches and
exercise one-channel ISO preservation after the protected main merge.

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

`automation/security/image-policy.json` blocks fixable High/Critical advisories
and known-exploited vulnerabilities. Native Syft inventory must identify the
exact image digest and a substantial RPM inventory. Bluefin-to-Fedora matching
requires the inventoried `fedora-release-common` major version as proof.
Grype database and Fedora/KEV feeds must be at most 48 hours old; promotion
requires evidence at most 24 hours old and evaluates the current policy again.
Scanner errors, incomplete inventories and expired evidence block publication.

Exceptions require a reviewed exact digest, component and advisory, justification,
reviewer, approval date and expiry within 30 days. They are committed changes,
never a workflow input. The scheduled **Audit published image security** workflow
rescans all four public channels daily and can also run manually. It reports
new vulnerabilities without automatically replacing or rolling back an image.
Release preparation runs a fresh enforcing scan of its qualified digest.

Bluefin base updates and candidate builds verify immutable base digests using
`sources/bluefin.pub` and its reviewed fingerprint policy. Publisher key rotation
requires review of both files. Explicit legacy Cosign image signatures match
bootc's container-signature policy. See [security implementation](security-implementation.md)
for deployment evidence and remaining upstream trust boundaries.


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
