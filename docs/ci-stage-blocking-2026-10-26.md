# CI stage blocking and source-proof rollout, October 26 UTC

PRs [270](https://github.com/closure-labs/finite/pull/270) and
[271](https://github.com/closure-labs/finite/pull/271) merged together at
`33195e5f051b9608ab5263449f5466b782e413e4`. Both exact heads had human approval;
the combined protected tree matched the reviewed head. The
[combined queue](https://github.com/closure-labs/finite/actions/runs/40262641076)
passed both local VM profiles and used 6,827 runner seconds. The superseded
[#270 queue](https://github.com/closure-labs/finite/actions/runs/40261544320)
was cancelled before duplicate qualification completed. Its 1,337 runner
seconds remain costs, not savings. No production publication was cancelled.

The [main run](https://github.com/closure-labs/finite/actions/runs/40268743648)
passed using 454 runner seconds. Natural
[decision reconciliation](https://github.com/closure-labs/finite/actions/runs/40269378232)
and [delivery health](https://github.com/closure-labs/finite/actions/runs/40269378251)
passed. Main selected no image jobs after complete source and selection results.
These are unmatched observations, not a before/after performance benchmark.

## First successful natural source comparison

The corrected read-only token wiring authenticated queue run `40262641076`,
source job `121378187387` and artifact `12624723791`. Its original ZIP digest is
`sha256:aeddd6958e9a8ff33af3a04756f7f1743e504c6d40ed04f429b33e0b9068549a`.
Both producer and consumer computed
`/nix/store/yk2xm7g12nf7lqlm5cs36im2halzhi7s-finite-ci-checks.drv`.
The native main receipt records `eligible: true`, `shadowMatch: true` and
`hit: false`: all source checks still executed.

| Main source job component | Seconds |
| --- | ---: |
| Complete source job | 367 |
| Nix setup | 35.259 |
| Authenticated source-proof lookup | 2.874 |
| Evaluate aggregate | 241.487 |
| Build aggregate | 62.554 |

The two aggregate phases used 304.041 seconds inside that job. These nested
measurements do not add to native runner occupancy. They identify a candidate
for reuse, not realized savings. This is one successful natural shadow
comparison out of five required. Keep repository mode `shadow`, require no
unresolved mismatch, and compare complete source-job costs before an enabled
canary. The earlier unknown lookup and authenticated diagnostic replay remain
outside the successful cohort. PR, queue, scheduled and manual checks remain
full; source proof grants no publication authority.

## Stage timing and observed blocking

The read-only cost report now retains each job's sole-runner intervals and
intersects absolute stage timestamps with those intervals. It reports the
known stage occupancy and unknown sample count alongside elapsed time,
frequency, profile, workflow, event and exact rollout revision. The Markdown
report now exposes that stage ranking as well as whole-job ranking.

This is a blocking lower bound from observed runner overlap, not a reconstructed
dependency graph or predicted savings. Concurrent required jobs can have zero
sole-runner occupancy and still determine workflow completion. Missing absolute
guest/security timestamps, incomplete native intervals and invalid placement
remain unknown. Failed stages retain their time and outcome. Second-precision
native timestamps allow one second of tolerance, clipped to the job boundary.
Nested intervals overlap and must not be summed.

An offline replay of the [original recent census](ci-gate-rollout-2026-10-26.md)
retains all 155 runs, 378 unique jobs and 48,971.597477 known runner seconds.
Every original stage duration, frequency, outcome and cohort is unchanged.
The following table pools cohorts only for prioritization; the retained JSON
keeps their original distinctions.

| Stage | Samples | Elapsed seconds | Known sole-runner seconds | Unknown placement samples |
| --- | ---: | ---: | ---: | ---: |
| VM acceptance | 10 | 9,319.442 | 650.339 | 0 |
| ISO construction | 10 | 7,113.218 | 0 | 0 |
| Actual `home-init` | 11 | 4,285 | unknown | 11 |
| VM installation | 12 | 4,270 | unknown | 12 |
| Historical combined `home-activation` | 10 | 4,140 | unknown | 10 |
| Evaluate aggregate | 14 | 3,664.871 | 3,398.040 | 1 |
| Image build | 9 | 2,783.619 | 250.007 | 0 |
| Build aggregate | 14 | 928.903 | 858.551 | 1 |

Historical `home-activation` includes startup checks, Homebrew, predecessor
preparation and fixture creation; it is not an isolated initializer. Unknown
placement is not zero time. ISO construction's measured zero means another job
was active throughout those samples; it does not establish that ISO work is
avoidable or outside the dependency critical path.

The [projection](ci-stage-blocking-2026-10-26.json.gz) has SHA-256
`eda53b737e6d7c0d93b7f387c551f5edf1d07cad2d46edfb96a269b2321a5d6d`.
It references the unchanged original census by hash and includes the native
queue/main projections, authenticated source receipts, cancelled work and
natural callback outcomes. Original reports and their measurements are retained.
No new native run, image or VM was started to populate the projection.

## Current work list

| Recommendation | Classification | Next action |
| --- | --- | --- |
| Duplicate proposal approval, shared health inspection and one release approval | completed | #265-267 merged; live release environment was activated and fully audited. Retain independent signing/publication checks. |
| Authority worker coalescing | awaiting rollout evidence | Native discovery/workers passed; observe natural bursts before claiming recurring savings. |
| Bounded process failure evidence and authority roles | completed | #270 is included in the successful combined rollout; malformed rows still fail. A future failure can use the new bounded row evidence. |
| Exact-commit source proof | awaiting rollout evidence | #271 main produced the first natural match. Keep shadow at one of five; do not create runs just to fill the cohort. |
| Stage blocking report | awaiting rollout evidence | Implemented; verify pinned aggregate and source-only selection. Use existing authenticated receipts without guest changes. |
| Installer-runtime reuse and guest closure transport | requires measurement | Substantial elapsed costs remain; prove avoidable, candidate-independent work before behavior changes. Preserve unseeded fresh installs and real bootc Home Manager activation. |
| Optional predecessor timeout | awaiting rollout evidence | Earlier source verification does not establish observed optional transfer execution. |
| Native release origin receipt | deferred | Existing measurements failed the adoption gate; retain original ZIP verification. |
| Same-build local OCI comparison, installer compression, Cachix writes and Grype database transport | deferred | Preserve earlier gates and disabled/stopped defaults. |

Use recent runs now. Preserve the original separate seven-day endpoint
`2026-10-30T05:01:17Z` and identify incomplete later cohorts. No local Nix
evaluation/build or VM run was used for this change. Focused regressions cover
parallel intervals, retry projections, failed/partial stages, unknown placement,
timestamp precision, skipped jobs and total cost conservation. Hosted pinned
`.#ci-checks` verification remains required.
