# CI gate rollout and recent costs, October 26 UTC

This is the current work list after the [October 25 gate plan](ci-gate-consolidation-2026-10-25.md).
The earlier reports retain their original measurements. Use recent natural runs
now; the original seven-day endpoint remains `2026-10-30T05:01:17Z` for a separate
complete-window assessment.

## Recent operating cost

The [retained census](ci-gate-rollout-2026-10-26.json.gz) covers runs created from
`2026-10-25T16:00:00Z` through `2026-10-26T00:56:41Z`, exclusive. Collection
finished at `00:58:10Z`. It contains 155 native runs and 378 unique jobs: 132 runs
succeeded, seven failed, one was cancelled, 14 were skipped and one was still
running. Known runner occupancy is 48,971.597477 seconds. No job duration is
missing; the active job is right-censored. Grouped totals conserve every known
native runner second, including failures and retries.

The compressed snapshot's SHA-256 is
`6e88eeec3a0b3b27400de184d24c6caebc2b76a50fbf2a0bc37f48b3a709fe97`.
Its cohorts retain workflow, event, profile, role and exact source revision.
Later revisions are separate rollout cohorts. The proposed role correction in
this change identifies authority discovery, legacy/matrix authority workers
and the event collector only within their native workflows. Other ambiguous
names remain unknown. This changes attribution, never native occupancy or
approval authority.

The receipt budget authenticated all 48 selected archives across 35 runs.
Nine additional relevant runs exhausted the budget and retain unknown stage
coverage; 111 other workflows were not selected for receipt transport. Native
job accounting covers all 155 runs regardless of that budget. No extra CI,
image or VM run was started to populate this report.

The table pools cohorts only to rank opportunities. Frequencies describe this
sample, not a forecast. Medians use completed jobs with positive occupancy.
Known sole-runner time is a lower bound on blocking within each workflow;
parallel work with zero sole-runner time can still be required. Exact dependency
DAG contribution remains unknown.

| Work | Jobs / runs | Runner seconds | Completed median seconds | Known sole-runner seconds | Unknown sole-runner jobs |
| --- | ---: | ---: | ---: | ---: | ---: |
| Upgrade/rollback qualification | 5 / 3 | 9,481 | 1,903 | 741 | 0 |
| Image build and local VM validation | 11 / 6 | 9,149 | 562 | 1,056 | 0 |
| Fresh qualification | 5 / 3 | 8,532 | 1,644 | 0 | 0 |
| Source contracts | 21 / 21 | 7,731.597 | 384 | 7,350 | 1 |
| Image security | 5 / 3 | 3,321 | 615 | 142 | 0 |
| CodeQL jobs, role unknown | 40 / 20 | 2,496 | 52.5 | 608 | 0 |
| Maintainer authority workers | 37 / 37 | 2,212 | 57 | 2,212 | 0 |
| Decision reconciliation jobs, role unknown | 23 / 23 | 1,764 | 178 | 1,764 | 0 |
| Delivery health jobs, role unknown | 20 / 9 | 683 | 53.5 | 421 | 0 |

Image/local-VM work and fresh/upgrade qualification account for 27,162 seconds,
55.5% of this sample. Source contracts contribute another 15.8% and have the
largest observed sole-runner interval. Twenty source jobs completed; the other
source job contributes measured elapsed occupancy without a completed median.

Authenticated nested stages include 10 VM acceptance intervals totalling
9,319.442 seconds, 10 ISO builds totalling 7,113.218, 11 `home-init` intervals
totalling 4,285 with one failure, and 14 aggregate evaluations totalling
3,664.871 with a 269.029-second median. These intervals overlap and have
incomplete receipt coverage: do not sum them or divide them into a disjoint
cost breakdown. Historical `home-activation` is the combined initialization
interval, including startup, Homebrew, predecessor preparation and fixture
creation. It is not the isolated initializer.

## Observed rollout and failures

- [#266 queue](https://github.com/closure-labs/finite/actions/runs/40222425206)
  and [main](https://github.com/closure-labs/finite/actions/runs/40222992115)
  passed using 404 and 481 runner seconds. The consolidated
  [healthy delivery job](https://github.com/closure-labs/finite/actions/runs/40225154308)
  used 67 seconds, one Nix setup and one authenticated same-job snapshot.
  An earlier healthy execution used 102 seconds across two jobs; this is an
  unmatched comparison, not a causal savings estimate. Its preceding failed
  health execution preserved the failed inspector outcome while preparation
  and audit reporting completed independently.
- [#267 main](https://github.com/closure-labs/finite/actions/runs/40228795496)
  passed using 408 runner seconds. The redundant `release` environment reviewer
  was removed after merge with no active or waiting official release. The
  administrator audit passed with complete policy coverage and no drift.
  Environment identity, main-only access, signing secrets, disabled
  administrator bypass and separate package-cleanup approval are preserved.
- The first [native discovery/worker execution](https://github.com/closure-labs/finite/actions/runs/40245003334)
  passed: discovery used five runner seconds without Nix, followed by one
  60-second target worker. Running writers are not cancelled. A natural burst
  demonstrating pending-event coalescing has not yet been observed.
- The [#265 main publication](https://github.com/closure-labs/finite/actions/runs/40219479618)
  used 10,003 runner seconds. All four VM phases passed, but aggregation rejected
  the source after #266 advanced main. Keep subsequent main changes behind
  active publication work to avoid making qualified work obsolete.
- [#268 main](https://github.com/closure-labs/finite/actions/runs/40232810950)
  used 10,873 runner seconds. `finite` promoted; `finite-dev` fresh installation
  failed because the desktop observer rejected a malformed or unlabelled process
  row. That error did not retain the offending row, so its cause remains unknown.
  The separately approved [same-candidate recovery](https://github.com/closure-labs/finite/actions/runs/40240085933)
  passed fresh installation, upgrade/rollback and promotion using 5,199 runner
  seconds. The failed execution remains in accounting.
- The first [#269 queue](https://github.com/closure-labs/finite/actions/runs/40245197650)
  used 5,489 runner seconds and failed on the `finite` Home Manager closure
  download: TLS errors were followed by HTTP 416. `finite-dev` passed. The
  completed source job produced an authenticated versioned configuration proof,
  but a failed whole producer workflow cannot authorize reuse. The unchanged
  approved head was requeued once for required correctness validation.

The #269 workflow edit explicitly requires both premerge VM profiles. An early
job list before downstream selection did not establish that images were
omitted. Preserve that coverage. The retry changes neither installer behavior
nor initialization order; each VM invokes initialization once.

This draft retains the bounded offending process row, its line number, original
length and truncation flag in a failed desktop observation. Process collection
still uses `comm`, with no command arguments. Invalid rows still return failure
and cannot become qualification evidence. This makes a recurrence diagnosable;
it does not identify the earlier bad row or waive its rejection.

## Current findings

The later [#275 main build](https://github.com/closure-labs/finite/actions/runs/40347208371)
and its [controller callback](https://github.com/closure-labs/finite/actions/runs/40349147958)
passed. Four natural main consumers have authenticated shadow matches, with
zero mismatches and one earlier unknown credential-wiring observation. Keep
shadow mode until five successful natural comparisons; no enabled reuse hit
has been observed.

The older [scheduled build](https://github.com/closure-labs/finite/actions/runs/40346577478)
correctly stopped at the stale-source preflight after main advanced. It produced
no security scan archives. Its [failed controller callback](https://github.com/closure-labs/finite/actions/runs/40347905716)
then spent 52 native runner seconds, including 24 seconds of Nix setup and
15 seconds in the controller step, before rejecting the unsuccessful no-image
job inventory. Those step intervals are nested within the job, not additional
costs. The callback optimization skips Nix, App token creation and collection
only after authenticating a failed build with no scan evidence. Production
savings remain unmeasured until a natural qualifying callback occurs. Retain
the failed build and callback costs; neither has been rerun for this report.

| Recommendation | Classification | Current action |
| --- | --- | --- |
| Remove duplicate proposal approval reads | completed | #265 merged; proposal verifiers retain approval, non-proposal governance keeps its explicit check, and revocation/eligibility regressions pass. |
| Share delivery-health setup and inspection | completed | #266 main and authenticated same-job snapshot passed, including independent failed-health reporting. |
| One manual release approval | completed | #267 merged; live environment activation and full administrator audit passed. Keep exact proposal approval and independent signing/publication checks. |
| Coalesce authority events by PR/target | awaiting rollout evidence | #268 merged and native discovery/worker execution passed; observe natural bursts before claiming recurring savings. |
| Exact-commit main source proof | awaiting rollout evidence | Four natural successful main comparisons; zero mismatches, one earlier unknown. Repository mode is shadow. Require five successful comparisons before an enabled canary. |
| Failed build callbacks without scans | awaiting rollout evidence | Skip controller setup only after a complete live native inventory proves no scan evidence. Preserve failed-run health reporting and strict collection whenever evidence is present or metadata is unknown. |
| Bounded process-error evidence and native authority cost roles | awaiting rollout evidence | Implemented in this draft with unchanged rejection and unique-job accounting; require hosted checks and normal rollout. |
| Installer runtime reuse | requires measurement | [Ranked ISO costs](ci-recent-costs-2026-10-24.md) remain substantial. Identify candidate-independent work and retain unseeded fresh installation before designing a behavioral change. |
| Guest closure transport | requires measurement | Separate downloads from activation and preserve actual bootc Home Manager activation. The cache transport failure does not establish a safe reusable closure design. |
| Optional predecessor transfer timeout | awaiting rollout evidence | Preserve [#238's source verification](ci-follow-through-2026-10-23.md); an actual execution of the optional timeout path has not been established by this census. |
| Native release origin receipt | deferred | The prototype exists, but [transport evidence](ci-transport-evidence-2026-10-24.md) did not meet the warm adoption gate. Retain original ZIP verification. |
| Installer compression and retained local OCI verification | deferred | Keep the stopped [compression diagnostic](ci-iso-compression-diagnostic.md); require an exact same-build dual export before OCI comparisons. |
| Automatic Cachix writing and Grype database transport | deferred | Remain disabled. |
| Complete seven-day assessment | requires measurement | Keep the original endpoint and incomplete later cohorts; use this recent census now. |

No local Nix evaluation/build or VM execution was used. Native collection used
four read-only workers, a 512 MiB cap and peaked at 120.3 MiB. Stage receipts and
source proof never grant release approval or publication authority. Fresh
security, signing, reservation, revocation and partial-publication checks remain
independent.
