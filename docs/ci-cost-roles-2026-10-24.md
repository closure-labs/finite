# Recurring workflow cost roles, October 24, 2026 UTC

The retained [baseline observation](ci-workflow-costs-2026-10-23.md) contains
1534 runs and 5818 unique native jobs from
October 9, 03:55 UTC through October 23, 03:55 UTC. This report reclassifies
the same observations; it does not recollect them. The original gzip remains
unchanged at SHA-256 `36124a090ffdd37172c2ff28a516caa23b7bd5acdbb7f9b341e42d796f8fed32`.
The [restatement record](ci-cost-roles-2026-10-24.json.gz) preserves exact
workflow/event/profile/source-revision cohorts, classification hashes and
the before/after conservation check.

Known runner occupancy remains **1144307 seconds** before and after.
The 36 jobs without runner durations remain unknown; 3 active jobs retain their
original right-censored values. Reclassification establishes no savings.

## Correct known native job labels

`Nix and runtime contracts`, `Documentation checks`, `Select checks` and
`CI gate` previously fell through to unknown because their display names are
not literal role suffixes. Recognize these exact native names as checks, docs,
selection and gate. New display names remain unknown. Historical monolithic
`Publish (PROFILE) / qualification / qualify` remains a separate qualification
role from current fresh/upgrade phases. Retired profile labels remain
`shared_or_unknown`; they are not assigned to current finite profiles.

| Restated work | Jobs | Runner hours | Known sole-runner hours | Unknown sole-runner jobs |
| --- | ---: | ---: | ---: | ---: |
| Nix and runtime contracts | 373 | 30.06 | 28.77 | 14 |
| Select checks | 373 | 2.52 | 1.24 | 14 |
| Documentation checks | 373 | 2.09 | 1.06 | 14 |
| CI gate | 367 | 0.53 | 0.51 | 12 |
| Historical monolithic qualification | 32 | 29.67 | 3.63 | 0 |

These counters include failed, cancelled and skipped work. Sole-runner time
is a measured lower bound on blocking occupancy, not an exact dependency
critical path. Unknown sole-runner intervals are not zero.

## Ranked baseline occupancy

All rows below are the build workflow. Event, role and profile remain distinct.
The machine record also separates each exact source revision. This table rolls
up only the historical baseline, rather than attributing later rollouts to it.

| Event | Role | Profile | Jobs | Runner hours | Median seconds | Known sole-runner hours | Unknown sole-runner jobs |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| push | qualification | shared_or_unknown | 26 | 24.98 | 3408.5 | 1.64 | 0 |
| pull_request | build | shared_or_unknown | 80 | 17.59 | 812.0 | 0.74 | 0 |
| push | build | shared_or_unknown | 94 | 13.89 | 503.0 | 0.05 | 22 |
| pull_request | build | finite-dev | 36 | 13.43 | 775.0 | 2.60 | 0 |
| push | security | shared_or_unknown | 88 | 13.02 | 675.0 | 0.31 | 22 |
| merge_group | build | shared_or_unknown | 58 | 12.98 | 827.5 | 0.33 | 0 |
| pull_request | checks | shared_or_unknown | 170 | 12.93 | 245.5 | 12.59 | 0 |
| pull_request | build | finite | 36 | 10.87 | 605.0 | 0.05 | 0 |
| merge_group | build | finite-dev | 23 | 8.68 | 798.0 | 1.50 | 1 |
| merge_group | build | finite | 23 | 7.51 | 586.0 | 0.17 | 1 |
| push | qualification-upgrade | shared_or_unknown | 14 | 7.41 | 1931.0 | 0.14 | 0 |
| push | checks | shared_or_unknown | 76 | 7.08 | 326.0 | 6.33 | 12 |

## Current work list

The baseline is earlier than the initial VM-tool rollout. It cannot establish
savings from #232, #237, #238, #240 or #243. Historical PR image rounds are
already removed by #232 and are not a new optimization proposal. Likewise,
monolithic qualification of retired profiles does not identify current installer
reuse opportunities. Preserve those measurements without reimplementing finished work.

The newly visible source aggregate has 373 jobs, 30.06 runner hours and at least
28.77 hours of sole-runner occupancy in this baseline. That cost and frequency
make it a recurring measurement priority alongside the current qualification
stages. Its evaluation, realization, transport and setup fractions remain
unseparated in this dataset; do not infer cache misses or change Nix/cache
behavior from a whole-job label. Candidate/tool/reuse values without receipts
remain unknown. The [natural qualification breakdown](ci-cost-selection-2026-10-23.md)
already isolates ISO construction and actual home-init; avoidable fractions
still require evidence before installer-runtime reuse or guest closure transport.

#243 merged through a source-only queue. This role correction naturally changes
the observer itself and retains the pinned aggregate; its queue/main outcomes
can later show the observer-path selection behavior without a synthetic report
change or a manually dispatched VM round. No post-change cost is claimed here.

The separate transport reporting work remains draft while the original matrix
continues. The unmatched warm pair is retained, and production keeps original
ZIP verification. The seven-day endpoint remains `2026-10-30T05:01:17Z`, with
later cohorts separate and incomplete. Cachix writing and Grype database
transport remain disabled.
