# CI stage rollout observations, October 23, 2026

#240 and #241 merged through the protected queue. This report joins native
receipts from naturally occurring runs; no VM was dispatched to populate it.
The [companion record](ci-stage-rollout-2026-10-23.json.gz) retains native job
identity, timestamps, archive digests, collector hashes and explicit coverage gaps.

## First split guest intervals

One observation per profile from [queue run 40023137137](https://github.com/closure-labs/finite/actions/runs/40023137137)
at `6f5401d0bffd42cdfb31739da0a9946d8e4c733e`. Both profiles passed local fresh-install
acceptance. These are nested intervals, not additive runner charges or matched
before/after savings. Integer zero denotes an observed interval below the
one-second timer resolution; a missing value remains unknown.

| Measurement, seconds | finite | finite-dev |
| --- | ---: | ---: |
| Complete image/VM job | 2345 | 2828 |
| Image construction | 469.981 | 611.581 |
| Local OCI export | 229.327 | 398.161 |
| Installer preparation | 20.845 | 16.477 |
| ISO construction | 713.152 | 704.749 |
| Complete VM acceptance | 709.247 | 884.799 |
| Guest installation within acceptance | 284 | 425 |
| Guest startup checks | 2 | 0 |
| Homebrew setup | 0 | 0 |
| Predecessor preparation; fresh lane is a no-op | 0 | 0 |
| Actual home-init | 319 | 339 |
| Persistence/customization fixtures | 0 | 1 |
| Historical combined initialization interval | 321 | 341 |
| Host cleanup before log export | 0 | 0 |

The complete queue used 5596 summed runner seconds.
Developer had 483 sole-runner seconds; standard had 0.
Sole-runner occupancy is a measured lower bound on workflow blocking, not a
reconstructed dependency DAG. Home initialization dominates its combined guest
interval, while ISO construction and acceptance remain larger whole-job work.
These data do not isolate home-init fetching, evaluation or realization. Keep
unseeded installation and actual bootc activation before proposing closure transport.

## Coverage and current main outcomes

| Run | Event | Source revision | Recorded outcome |
| --- | --- | --- | --- |
| [40023137137](https://github.com/closure-labs/finite/actions/runs/40023137137) | merge_group | `6f5401d0bffd` | success |
| [40029772409](https://github.com/closure-labs/finite/actions/runs/40029772409) | merge_group | `6ef15e7e2d2d` | success |
| [40029771884](https://github.com/closure-labs/finite/actions/runs/40029771884) | push | `6f5401d0bffd` | failure |
| [40032009520](https://github.com/closure-labs/finite/actions/runs/40032009520) | push | `6ef15e7e2d2d` | in_progress |

The later queue selected image validation without the VM round. Its shorter
jobs are a different execution cohort, not evidence of faster VM work.

The first main run passed both native scans and reported covered security
admission, then both signing steps failed after the #241 merge advanced main.
Neither qualification nor promotion ran. The failures produce no additional
message; the well-formed digests, passed key preflights and exact-source check
are consistent with the source-currency guard stopping an obsolete main run.
Retain that guard; do not resume the old candidate to manufacture rollout evidence.

The latest main run was active at collection. Its runner occupancy is
right-censored; later qualification/promotion results are outside this snapshot.
Large security archives exceed the bounded receipt limit and remain unknown
in the machine record, rather than becoming zero work or cache misses.

## Reader correction and remaining evidence

The first collector matched nested guest rows only to production qualification
roles, so it omitted valid `vm-local` rows from queue build artifacts. Bind them
by native profile, producing attempt and build role. Include host installation,
fixture and cleanup counters from the same authenticated VM evidence. Reject
mismatched phases and duplicate markers; deduplicate repeated receipts without
charging native jobs again. Missing legacy statuses remain unknown, not failures.

Both raw queue archives were authenticated before this correction and reused
for the corrected join; no producer was rerun. Focused regressions exercise
both profiles, separate queue/production roles, duplicate rows, failed stages,
legacy unknown statuses and phase mismatches.

The seven-day endpoint remains `2026-10-30T05:01:17Z`. This snapshot is incomplete,
and later source revisions remain separate cohorts. Installer runtime reuse and
guest closure transport still require avoidable-cost evidence. The transport
diagnostic is a separate new packet derived from the authenticated two-profile
`0.8.3-dev` products; production still uses strict original ZIP verification.
No matched transport results or adoption are claimed here. Automatic Cachix
writing and Grype database transport remain disabled.
