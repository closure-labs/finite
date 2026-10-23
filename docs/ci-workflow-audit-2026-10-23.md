# CI delivery and cost audit: 2026-10-23

This audit uses live GitHub metadata, authenticated image artifacts and the
current controller code. Its [versioned receipt](ci-workflow-audit-2026-10-23.json)
records repository settings, candidate sources and the download reproduction.
Reports are discovery evidence and grant no approval or publication authority.
Historical optimization reports supply background only.
The continuation receipt records production tool realization at 05:01:17 UTC
and the separately validated Foundation 0.3.1 preparation.

## Execution baseline

| Native execution | Source / decision | Selected work | Observed result |
| --- | --- | --- | --- |
| [PR 229](https://github.com/closure-labs/finite/pull/229) | `c3e5fbc3b2d723a00a94aebda549ef9e123d494b` | Both profiles; pinned VM tools | Merged at 04:23:05 UTC; queue validation passed |
| [Queue 1055](https://github.com/closure-labs/finite/actions/runs/39893873274) | `5b302cc0d165a6421cec9b1dbc4cb11caddbbd07` | Both validation profiles | Both validation profiles and CI gate passed; no publication authority |
| [Publication 1054](https://github.com/closure-labs/finite/actions/runs/39891524132) | `059e77b178d31b74d66471f11775b6f82bd3518c`; request `d0066566ccebdd6268b21cb6f38154d84453c3306d4365eab54364bbad8a1b60` | `finite` | Signing passed; fresh qualification failed; upgrade passed; promotion skipped |
| [Dispatch 1056](https://github.com/closure-labs/finite/actions/runs/39895945016) | Same execution source; request `681efa873bec849f1a0a0ad2347006cc19d8b7eda79df1ebb3a129878b4975ba` | `finite-dev` | Both VM phases passed; aggregation rejected changed main release inputs; promotion skipped |

Both dispatches resume original [build 39856819751](https://github.com/closure-labs/finite/actions/runs/39856819751)
at image source `cb777f8334764dcb6c2609cb9d830938087aa636`, attempt 1.
The standard candidate is
`sha256:190c26d14e736fe0bdef4546fd94a132e0186acf53bbf2095dee4fe68d1e9760`;
the developer candidate is
`sha256:e31704e367d180b2d1d88d16656a55f33e532bf5292518fd64396333cb85465a`.
The receipt includes original job IDs, artifact digests and build identities.
The request hashes identify dispatches, not the underlying human proposal;
current native authority must still be verified independently.

**Confirmed:** 1056 is a successor dispatch for the other profile, not recovery
of 1054. A successful build or signature cannot stand in for qualification or
publication. No rebuild, redispatch, approval, retag or asset cleanup was issued
by this audit. The frozen `0.8.2-dev` execution remains untouched; current main's
version is `0.8.3-dev`.

**Rollout:** 229 merged as `5b302cc0d165a6421cec9b1dbc4cb11caddbbd07`
at 2026-10-23 04:23:05 UTC. Its first main push execution is
[1057](https://github.com/closure-labs/finite/actions/runs/39900028671). Its
[standard qualification preparation](https://github.com/closure-labs/finite/actions/runs/39900028671/job/120249676294)
realized and verified the pinned Nix tools at 05:01:17 UTC: QEMU 10.2.4,
Skopeo 1.22.2, Xorriso 1.5.6 and the pinned Secure Boot firmware/tool manifest.
The native job and retained log bind this to main source
`5b302cc0d165a6421cec9b1dbc4cb11caddbbd07`, attempt 1, runner image
`20261012.334.1`, and candidate
`sha256:1c5a6d2969165273a856c0505ea1abcd2abd69fbf1fefce95139662dde40bb75`.
The [developer preparation](https://github.com/closure-labs/finite/actions/runs/39900028671/job/120252764021)
verified the same pinned tool manifest at 05:11:51 UTC. Both profiles' production
tool realization, fresh-install and upgrade/rollback qualification and promotion
all passed. Native run 1057 completed successfully at 05:45:24 UTC. Both
aggregate archives were authenticated against their native SHA-256 digests;
their receipts retain candidate, predecessor, source and exact tool context.
Its reviewed [benchmark run](https://github.com/closure-labs/finite/actions/runs/39888869006)
retains summary artifact `12474508103`, digest
`sha256:e5ed0b8d3c43f229095779fd8adca801ca9b228886db6eecfbe419f5b7a5460d`.
The published PR describes complete benchmark-job medians of 62s for apt, 51s
for minimal apt and 40s for Nix. These provisioning results do not measure
complete image/VM workflow savings. The summary archive was independently authenticated against its native digest.
The subsequent read-only health observation reports both channels healthy.

## Interrupted download and recovery boundary

The failed [fresh job](https://github.com/closure-labs/finite/actions/runs/39891524132/job/120216173497)
logged an interrupted NAR download, then a retry from offset 34,267,403 and HTTP
416 for the same `cache.nixos.org` URL. The resulting bitwarden substitute
failure propagated into the Home Manager generation. This trace shows a resume
transport failure; it does not show a missing object, authorization rejection,
hash mismatch or signature rejection.

A controlled loopback fixture using Determinate Nix 3.23.3 / Nix 2.35.3 advertises
byte ranges and interrupts a 2,900,000-byte response halfway. Nix requests
`Range: bytes=1450000-`; the fixture returns 416; Nix exits 1. A fresh command
requests the whole object and verifies the expected hash. The recovery helper
completed that sequence in about 2.1s including the two-second backoff. The
receipt retains requests, statuses, elapsed times, output hashes and tool version.
This exercises Nix's shared downloader; full guest acceptance remains separate.

The separate [Foundation change](https://github.com/closure-labs/foundation/pull/11) wraps only the existing realization command.
It allows three total attempts, two/four-second backoff and one 900-second
deadline including nested retries. A 416 needs prior interruption/resume proof
for the exact URL in that attempt. Authorization, integrity, evaluation, build
and signal failures remain terminal. Configuration generation, provisioning and
activation are never retried; recovery never deletes user configuration or
purges a shared cache. Diagnostics stream throughout each attempt.
It merged as `3770f60f145e92cae8306a3e7883cd7a8d6d6677`.
The separate [0.3.1 preparation](https://github.com/closure-labs/foundation/pull/12)
also makes unknown root errors terminal when a transient transfer appears in
the same log. This closes a reproduced evaluation-error classification gap.
The final helper still accepts 1054's actual interrupted-resume/substitute
cascade. Its real fixture uses the failed guest's Nix 3.23.3 / 2.35.3 client.
Local and [hosted CI](https://github.com/closure-labs/foundation/actions/runs/39902662603)
pass: 156 Python tests, full Nix builds and selectable schemas 2/3 on both
Bluefin foundations. Finite's Home Manager contracts pass with a temporary
override to immutable preparation head
`f9d56cd9633e8d60adbbc1ea6df8a863b6f371e9`. The candidate archive contains the
expected helper and unchanged 0.3.0 dependency lock. PR 12 merged as
`563f970af88fdd737b5cde5af0a64ac1d7329a98`; main CI and release validation
passed. The new annotated `v0.3.1` tag selects that exact commit. Its draft source
archive, native asset hashes, checksum file and notes were independently verified.

**Confirmed release-review defect:** a mixed diagnostic log caused wrapper exit
137 to enter transport recovery. The controlled regression observed two attempts
and a successful second result where the first terminal exit should have stopped
work. The 0.3.1 draft remains unpublished and explicitly marked not to publish;
its shared Git tag and assets are preserved. The release checklist requires a new
version after sharing a tag. The corrected
[0.3.2 preparation](https://github.com/closure-labs/foundation/pull/13) permits
recovery only for ordinary Nix failure exit 1 and rejects kill/OOM diagnostics
even when a wrapper returns 1. Negative signals and positive wrapper/usage exits
remain terminal. Its pinned local suite passes 158 tests and full Nix profile
validation. The real transfer fixture and Finite Home Manager contracts pass
against immutable candidate `aa506df0e8e77e675782da97afd8487e54a527ae`.
PR 13 merged as `235c34d7e507f00c2df6b0102bcdb54a4c04c5e2`; main CI and the final release workflow passed. [Foundation 0.3.2](https://github.com/closure-labs/foundation/releases/tag/v0.3.2) was published at 06:22:31 UTC after its archive was independently reproduced byte for byte and its native hashes, checksum file, notes and tag identity were verified. Both stable-channel advancement executions passed and select that same immutable commit. This separate Finite adoption pins that release; new guest qualification remains required.

**Recovery blockers:** 1056 finished with the expected stale-execution rejection;
1057 completed successful publication for both profiles. Directly resuming
1054 also fails the supported original-build contract: its preparation/build
steps were skipped because it was already a resume. The supported origin is
39856819751 with the standard digest above, subject to live source ancestry,
exact image identity, retained artifact/provenance and current human authority.
Merged 229 changes the image workflow, which is hashed into the existing
image-input identity. The old candidate therefore cannot satisfy current source
identity checks; it must not be relabeled to bypass them.
An immutable candidate cannot acquire a new guest helper. Publish Foundation
through its existing release process and qualify a separately reviewed Finite
dependency update; that is a new candidate, not recovery of the recorded one.

## Workflow and authority inventory

All 37 workflows were inspected for triggers, job dependencies, concurrency,
permissions, artifacts, cache configuration and recovery inputs. The retained
native cost report includes workflow paths and step timings for observed jobs.

| Area | Current boundary | Finding |
| --- | --- | --- |
| Build Finite | PR/queue validation; main push, schedule and manual publication | Validation cancels only superseded validation; `finite-publication` does not cancel active publication |
| Human decisions | Trusted main collector, configured App check and current Super Admin approval | Live main rules bind `Maintainer decision authority` to App 5384448 and `CI gate` to GitHub Actions; single-entry queue enforced |
| Early validation | Shared exact Git-tree comparison before setup and again before image setup | Fixed: changed governed paths, rename sources, contents, modes, additions/deletions and moved heads fail early with rebase/review guidance; no authority granted |
| Decision reconciliation | Serialized workflow, CAS journal, 900-second lease, native dispatch marker | Existing lost-response recovery and duplicate prevention retained; added a publication-busy recheck after claiming and before dispatch |
| Paired preparation | Separate serialized workflow and same-source qualification/ISO requirements | Fixed: a successful preparation no longer automatically redispatches when its proposal is not visible; inspect/recover its packet explicitly |
| Official publication | `finite-official-release`, reservations, CAS lease, staged uploads and immutable commit | Existing staging/commit, lost-response and partial-publication recovery contracts retained; no automatic cancellation |
| Protected signer | Native `release` environment | Live environment requires the pinned Super Admin team; signing and publishing remain separate |
| Health | Main-only metadata correlation and authenticated identity artifacts | Existing failure, blocked approval, partial, published, missing/forged identity cases covered; build success never establishes release success |
| Read-only cost observer | Weekly/manual; existing read-only audit App; no signing, publishing or cache-write credentials | Added; records failed/cancelled/active work and reused native job IDs without granting authority |
| Cache policy | Optimized store snapshots and authenticated inventory/qualification reuse | Live variables enable these; automatic Cachix writing is false; Grype DB cache variable is absent and defaults false |
| Lock updates | Existing weekly reviewed updater | Unchanged |

Live Actions settings require SHA pins, selected actions, read-only default
workflow permission and prohibit workflow approval of PRs. The public
`FINITE_CI_AUDIT_ROLLOUT` variable now records `2026-10-23T05:01:17Z` for the
verified first production tool realization. The existing workstation operator
credential set this observation timestamp; App permissions were not expanded.
The health App token's requested permissions remain read-only;
the cost observer uses the existing read-only audit App through SecretSpec and
clears its private credentials after minting. It receives no signing, publishing
or cache-write secret. The existing Administration-read token scope can read
this public repository's native run/job metadata; that behavior was verified
without adding App permissions. The 1,534-run baseline exceeds the default
workflow token's [1,000-request hourly allowance](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api),
so collection uses the App token's separate allowance.

## Measured cost baseline and unresolved experiments

The [14-day table](ci-workflow-costs-2026-10-23.md) covers runs created from
2026-10-09 03:55 UTC through 2026-10-23 03:55 UTC. The complete versioned
[JSON report](ci-workflow-costs-2026-10-23.json.gz) contains 1,534 runs and 5,818
unique native jobs, totaling 1,144,307 observed runner seconds. It includes
218 failed, 79 cancelled and one startup-failure run. It also retains skipped
and active work. Runner occupancy is not billed cost. Category/profile rows
share run IDs and must not be added to obtain unique run counts.

Fifty-nine jobs have timing anomalies, retained with unknown durations rather
than clamped values. Native steps expose setup and post-job costs, but composite
cache restore/save substeps and internal download retries are unavailable in
this inventory. Native run attempts identify workflow reruns. Exact candidate,
runner-image/tool versions and inventory reuse eligibility/hits require producer
receipts; missing historical values remain unknown. Qualification eligibility
is observed from context setup and a hit requires its conditional reused-evidence
upload; successful lookup alone is not counted as reuse. No percentile estimates
or speed claims are made from these mixed cohorts.

The new read-only workflow uses the recorded rollout timestamp to retain a
14-day pre-rollout baseline and seven days of observations after its controller
PR merges. Its weekly observation on October 30 can cover the full window ending
at 05:01:17 UTC. Earlier observations report `complete: false`.
The live read-only health observation correctly separates 1056's failed
qualification aggregation from the already-published release inventories;
legacy executions without identity remain explicitly uncorrelated.
After run 1057 completed, the same read-only collector reported healthy delivery
and retained both new qualification/promotion identities. The receipts preserve
the earlier failed observation separately.

**Requires measurement:** production retains immutable registry-pull verification.
The pinned BlueBuild path currently chooses one exporter and retains no exact
same-build OCI archive. Existing registry diagnostics therefore do not establish
local export equivalence or savings. The local OCI comparison remains unrun;
there is no adoption recommendation. Its draft experiment must retain exact
published manifest/config/compressed layers, platform, unchanged signatures and
security checks, then run five matched warm pairs and one cold pair for each
profile. Include export, retention, transfer, import, verification, setup,
cleanup and native complete-job costs. Adopt only if both profiles pass every
check, warm complete-job medians improve by at least 10% and 30s, and cold cost
regresses by no more than 10%. Otherwise keep registry verification.

Cachix writing and Grype transport remain disabled. Each needs a separate
measured proposal covering reader and writer costs, failures and retention.
Reader cache hits alone cannot establish net workflow savings.

## Validation and rollback

Focused regressions cover shared governed-tree semantics, moved heads, native
pagination/timing anomalies, failed/cancelled work, reused job accounting,
qualification hit classification, preparation idempotence and publication that
starts after a dispatch claim. Existing aggregate suites exercise revoked review,
stale security evidence, competing reservations, candidate resume, stage without
publication, commit without asset mutation, lost responses and partial recovery,
plus failed/waiting/partial/published/missing/forged publisher identities.

The pinned `.#ci-checks` aggregate and repository text-style/Markdown-link
checks passed locally. Finite's
[standard PR validation](https://github.com/closure-labs/finite/actions/runs/39900947347/job/120244000085)
passed; its retained archive matches native SHA-256
`b3b2e290247fd162bf75c35453f2d15079aec42589052ba2a1d0c236ec12d1b8`.
The reviewed acceptance receipts confirm Secure Boot, encrypted root and
preserved Nix state/Home Manager customization. The
[developer PR validation](https://github.com/closure-labs/finite/actions/runs/39900947347/job/120243999964)
also passed, with native archive SHA-256
`82a9b736cd83e581cb6520dcdb19f5e2b8ba34e0c2153f92af96e3f047dfb882`.
Both acceptance archives were authenticated and reviewed. Protected queue run 1059 passed both profile VMs and CI gate; PR 230 merged at 06:18:55 UTC as `04cb70543c44aeb16da662c4bbb3dfe26775ac8c`. Foundation 0.3.2 pinned CI, full Nix validation and
release metadata checks passed locally, including 158 Python regressions;
its hosted PR, merged-main and tagged-release checks also passed. The separate Foundation suite covers interrupted transfers, successful
retry, attempts/deadline exhaustion, terminal errors, process termination and
preservation of partially initialized configuration. Hosted logs and retained
artifacts must be reviewed before either PR becomes ready. A later Finite
Foundation pin requires both fresh-install and upgrade/rollback qualifications,
including Secure Boot, enforcing SELinux, both Nix sockets and Home Manager.

Rollback the controller/reporting commit through the normal reviewed path to
restore previous scheduling/preflight behavior; disabling the cost workflow
requires no credential or asset cleanup. A Foundation rollback restores the old
realization command; user configuration requires no deletion or migration.
Never roll back by overwriting tags, approved payloads, reservations or published
assets. Remaining blockers are recorded-candidate source identity, both-profile
qualification and promotion of the separate Foundation pin, the unrun OCI experiment, unavailable historical substep/reuse
detail and the elapsed seven-day observation window.
