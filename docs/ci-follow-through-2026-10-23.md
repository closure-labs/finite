# CI rollout follow-through, October 23, 2026

The completed [#237 queue execution](https://github.com/closure-labs/finite/actions/runs/39990091392)
validated both profiles at `a250b76a01e9a6dd8e00d8ec8160f11e0d81aed4`.
The first [main execution](https://github.com/closure-labs/finite/actions/runs/39997829647)
then passed both fresh-install and upgrade/rollback qualifications, both
promotions and the final CI gate. Native
promotion results and complete workflow costs are recorded in the
[companion evidence](ci-follow-through-2026-10-23.json). Queue candidates are
local validation images; main candidates have their own recorded immutable
identities. Neither result substitutes for another candidate's acceptance.

## Where the queue time went

One observation per profile, seconds, including failed or cancelled work if any.
Both queue jobs completed successfully on Ubuntu 24.04 image `20261012.334.1`,
using the pinned Nix VM tool manifest and Determinate Nix 3.23.2. These are
complete native job durations and nested producer measurements, not matched
before/after savings or billed cost. Nested rows must not be summed twice.

| Measurement | finite | finite-dev |
| --- | ---: | ---: |
| Complete image/VM job | 2028 | 2950 |
| Payload staging | 9.049 | 4.204 |
| Image construction | 387.093 | 615.790 |
| Runtime checks | 13.579 | 18.461 |
| Local OCI export | 195.910 | 312.185 |
| Installer preparation | 17.015 | 22.190 |
| ISO construction | 571.576 | 807.634 |
| VM acceptance, including guest operations | 674.236 | 991.153 |
| Guest installation, within acceptance | 267 | 463 |
| Combined guest initialization, within acceptance | 326 | 402 |

The two evidence archives are 126,074 and 134,462 bytes. Their native archive
SHA-256 digests were checked before reading them; neither contains an ISO.
Queue validation already constructs and boots the ISO on the same runner.
Removing an assumed upload/download between those steps would remove no work.

The complete queue workflow took 3,338 seconds elapsed and 5,368 summed runner
seconds. Main took 4,169 seconds elapsed and 11,105 summed runner seconds.
These totals include selection, documentation, source contracts and the gate.
The companion record sums all native runner times
and queue delays separately from elapsed wall time. Independent CodeQL and
authority workflows are outside that sum. The 14-day/7-day observer remains the
source for repository-wide totals including failed, cancelled and recovery work.

## What the first main run proves

Both profiles passed fresh installation and upgrade/rollback with Secure Boot,
encrypted root, enforcing SELinux and the existing Nix daemon/socket contracts.
The retained Home Manager receipts report successful customization and Nix
state checks before and after upgrade. The combined guest initialization interval measured
359 seconds on standard and 586 seconds on developer. The predecessor guest's
combined initialization measured 348 and 339 seconds. The historical `home-activation` timer includes startup checks, Homebrew setup,
predecessor preparation, `home-init` and persistence/customization fixture
creation. It does not measure `home-init` alone. These observations identify
substantial guest work; they do not isolate fetch, evaluation or realization
cost, nor justify retrying the initializer or deleting partially created homes.

Both predecessor ISO lookups reported a context miss and reconstructed an
installer for the same signed predecessor image. The standard lookup took
23.712 seconds; native logs report predecessor ISO generation of 730 and 734
seconds for standard and developer. The restored-image optimization therefore
has no compatible post-rollout hit in this execution. Full qualification reuse
remains stricter than pristine predecessor ISO reuse.

The merged health implementation was also exercised through `inspect()` against
live native APIs using a short-lived repository token with only contents,
pull-request and Actions read permissions. While developer promotion remained
active, it reported that phase explicitly and retained the earlier completed
build failure. It separately identified the already published approved release.
That local observation did not run reconciliation, dispatch a workflow or supply
signing/publication/cache-write credentials. It is separate from a hosted health
workflow artifact.

The subsequent [hosted health execution](https://github.com/closure-labs/finite/actions/runs/40007361246)
completed successfully. Its digest-verified artifact reports healthy status, no
active builds, and both latest qualifications and promotions bound to
`39997829647`. It also retains the independently correlated published release
and identifies older executions lacking producer identity as uncorrelated.

## Reconsider whole paths before adding caches

| Path | Decision and next evidence |
| --- | --- |
| Ordinary PR image/VM round followed by the same queue round | Already removed by #232; source checks remain on PRs and both profiles remain mandatory in the protected queue |
| Repeated root output composition for payload identity and staging | #237 uses the same locked payload entry for both; mandatory aggregate proves exact derivation equality with the public output |
| Long optional predecessor download | #238 gives the exact archive GET one 600-second attempt before same-image installer reconstruction; authorization and integrity errors remain terminal |
| Full original product ZIP fetched again after OCI hydration | A native producer-bound receipt could remove a redundant bulk read; the [ISO transport proposal in #238](https://github.com/closure-labs/finite/blob/e11c312db49bbe09c4e7b030fd60b31978ca39b3/docs/iso-transport-2026-10-23.md) remains unimplemented and needs exact-packet correctness and complete-job measurements |
| Reconstructing the installer runtime for each candidate | Measured ISO construction is substantial; the pinned installer bakes in candidate origin/tag, so a reusable base requires a qualified installer refactor and cannot be enabled by swapping an OCI directory |
| Cold Home Manager initialization in every required OS lane | Keep actual bootc activation coverage; investigate guest fetch/evaluation/realization timings before changing closure transport. Foundation builds alone do not exercise OS activation, persistence or SELinux |
| Retained OCI export instead of immutable registry verification | Unadopted; no usable exact dual-output alternative has passed the five warm/one cold comparisons per profile |

Queue admission after the parent PR merges does not depend on completion of its
main publication. #238 entered the protected queue while #237 completed its
publication. Source/authority preflights and publication-current checks still
apply. Do not cancel active publication or weaken those checks to create overlap.

## Current findings

Historical reports retain their original measurements. This table is the current
work list; a successful source check is separate from observed production use.

| Recommendation and evidence | Status | Next evidence |
| --- | --- | --- |
| Remove duplicate PR image/VM rounds ([architecture](ci-architecture-2026-10-23.md), #232) | completed | Keep protected queue coverage for both profiles |
| Direct equivalent payload evaluation ([payload report](ci-payload-evaluation-2026-10-23.md), #237) | completed | Exact derivation equality and both main promotions passed |
| Correct predecessor context matching ([predecessor report](ci-predecessor-2026-10-23.md)) | completed | Preserve authenticated exact-image restore checks |
| Bound optional predecessor transfer ([ISO audit](iso-transport-2026-10-23.md), #238) | awaiting rollout evidence | Queue/source checks passed; first main selected no images and did not execute the timeout path |
| Split guest initialization and measure all main qualification stages | requires measurement | Observe startup, Homebrew, predecessor, home-init and fixture intervals on natural runs |
| Rank recurring work by native runner occupancy and critical path ([cost baseline](ci-workflow-costs-2026-10-23.md)) | requires measurement | Join bounded receipts, preserve unknowns and distinguish later rollout revisions |
| Reuse installer runtime ([architecture](ci-architecture-2026-10-23.md)) | requires measurement | Stage breakdown must identify avoidable cost before any behavior change |
| Transport guest closures ([reuse results](new-os-reuse-results.md)) | requires measurement | Preserve unseeded installs and actual bootc Home Manager activation |
| Replace duplicate release ZIP read with native origin receipt ([ISO audit](iso-transport-2026-10-23.md)) | requires measurement | Separate draft, exact-packet correctness, five matched warm pairs and one cold pair |
| Retained local OCI verification ([rollout](ci-rollout-2026-10-23.md)) | deferred | Exact same-build dual export required before comparisons |
| Automatic Cachix writing and Grype database transport ([reuse experiments](reuse-timing-experiments.md)) | deferred | Remain disabled |
| Seven-day assessment | requires measurement | Finish after 2026-10-30T05:01:17Z; later rollouts are separate incomplete cohorts |

The #238 [queue run](https://github.com/closure-labs/finite/actions/runs/40004291051)
and first [main run](https://github.com/closure-labs/finite/actions/runs/40011839730)
both succeeded. Main intentionally selected no images, so qualification jobs
were skipped. The source checks validate the timeout implementation; these
outcomes do not establish execution of the optional transfer in production.

## Remaining observations and rollback

The seven-day window ends October 30 at `05:01:17Z`. It is incomplete. Keep
automatic Cachix writing and Grype database transport disabled. A successful
reader hit alone does not establish net workflow savings. Preserve the frozen
`0.8.2-dev` execution and existing published products.

The interrupted #235 candidate was not resumed, rebuilt as a substitute or
redispatched by this audit. These later executions have their own source and
candidate identities. The original incident, authority constraints and recovery
blockers remain in the earlier reports.

This follow-through changes discovery documentation only. Roll back this report
independently; implementation rollback instructions remain in the payload,
predecessor and ISO transport incident records. A future transport optimization
must retain legacy verification, native approval, fresh security admission,
protected signing, reservations and immutable assets.
