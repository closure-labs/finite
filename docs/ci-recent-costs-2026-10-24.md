# Recent CI costs and next changes, October 24 UTC

Act on recent evidence now. This interim snapshot covers runs created from
`2026-10-24T05:00:00Z` through `2026-10-24T20:43:16Z`. It contains 172 native runs
and 485 unique jobs, including 145 successful, eight failed, four cancelled,
14 skipped and one unfinished run. Known runner occupancy is 85,975.331 seconds;
two job durations remain unknown and one job is active/right-censored.

The [retained snapshot](ci-recent-costs-2026-10-24.json.gz) preserves exact
workflow, event, profile, role and producer-revision cohorts. Its SHA-256 is
`55313350f7e78667ff5d0493b20bc29b47f7463a2080998b527633619a52ecb0`. Native run/job/attempt identities
were validated, every job ID is unique, and grouped cost conserves the full
known occupancy. The receipt budget selected 40 archives and authenticated/read
34; six oversized archives were skipped. Missing stage/reuse coverage stays
explicit. Revisions are rollout cohorts, not causal explanations.

Twelve explicitly named benchmark runs used 21,117 runner seconds. They remain
in total accounting but are separate from the 160 operating runs, which used
64,858.331 seconds. Operating workflows can still include one-off manual work;
these frequencies describe this sample and are not workload forecasts.

## Ranked recurring work

The table pools cohorts only to rank where investigation pays off. The retained
JSON keeps each event/profile/revision separate. Medians exclude zero-occupancy
skipped jobs. Sole-runner time is a measured lower bound on blocking within its
own workflow, not exact dependency-DAG contribution; incomplete coverage remains
unknown. A verifier's whole single-job workflow being sole-runner time does not
mean it delayed image publication by that amount.

| Work | Jobs | Known runner seconds | Median occupied job seconds | Known sole-runner seconds | Jobs with unknown sole-runner coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| Image and local VM jobs | 14 | 19,944.3 | 825.0 | 2,122 | 4 |
| Fresh qualification | 6 | 10,091.0 | 1,694.5 | 183 | 0 |
| Upgrade/rollback qualification | 6 | 9,528.0 | 1,563.0 | 328 | 0 |
| Source contracts | 19 | 6,979.0 | 374.0 | 6,157 | 2 |
| Image security | 8 | 5,878.0 | 607.5 | 61 | 2 |
| Authority verifier (role unknown) | 39 | 2,235.0 | 56.0 | 2,235 | 0 |
| CodeQL (role unknown) | 36 | 2,173.0 | 54.5 | 405 | 0 |
| Decision proposals (role unknown) | 24 | 1,678.0 | 193.0 | 1,678 | 0 |

Image/local-VM jobs and production fresh/upgrade qualification account for
39,563.331 seconds, 61.0% of operating occupancy. Source contracts are the next
large repeated blocking component: 6,979 seconds across 19 jobs. Of the eight
source jobs with authenticated phase receipts, aggregate evaluation totals
2,016.005 seconds with a 253.591-second median. These nested evaluation times
must not be added to job occupancy. The earlier paired Home Manager evaluation
trial did not improve complete-job cost; retain serial evaluation.

## What the stages establish

Three recent production runs supply all twelve successful fresh/upgrade phase
receipts: [40066733156](https://github.com/closure-labs/finite/actions/runs/40066733156),
[40087186086](https://github.com/closure-labs/finite/actions/runs/40087186086) and
[40094832162](https://github.com/closure-labs/finite/actions/runs/40094832162).
Their complete VM acceptance totals 11,094.159 seconds (median 881.794).
Eight observed ISO builds total 5,505.538 seconds (median 693.179); other upgrade
phases can reuse a pristine predecessor ISO. Candidate-dependent Lorax work,
reuse eligibility and missing rows must not be inferred from the absence of
an ISO stage. Preserve fresh installs and actual bootc Home Manager activation.

The naturally occurring [PR 250 queue run](https://github.com/closure-labs/finite/actions/runs/40118761949)
provides a local export comparison target, without claiming matched speedups:

| Local VM stage | finite seconds | finite-dev seconds |
| --- | ---: | ---: |
| Docker image to OCI archive | 206.925 | 532.785 |
| Installer preparation | 16.322 | 22.666 |
| ISO construction | 601.558 | 776.498 |
| Complete VM acceptance | 670.189 | 994.443 |

The two exports consumed 739.710 seconds, 12.5% of that workflow's 5,916 runner
seconds. Its profiles used different Ubuntu images (`20261023.334.3` and
`20261012.334.1`), so the difference cannot isolate a causal optimization effect.
Earlier measurements already identified export work; this run corroborates its
cost. Retained same-build dual-output OCI verification remains deferred until a
usable exact export exists. Registry-only diagnostics do not establish that
alternative's equivalence or savings.

## Current actions

| Work | Classification | Action from recent evidence |
| --- | --- | --- |
| Host-only timing helper image selection | Completed in this change | Preserve OS identity on later timing-only edits; still invalidate qualification reuse and require both premerge VM profiles. The identity implementation itself causes a one-time rollout change because its source remains hashed. |
| Child CPU and block-I/O observations | Awaiting rollout evidence | Record waited-child CPU seconds and block operation deltas alongside wall time, including failure/unknown results. Independent Docker/BuildKit daemon work is outside this scope. |
| Early usable-KVM checks and host capacity (#251) | Awaiting rollout evidence | Merged at 20:49 UTC after both premerge profiles passed. Follow natural main qualification; a source-only main run cannot establish execution of the host probe. |
| Local OCI export and Lorax runtime reuse | Requires measurement | Use these ranked costs now to identify compression, disk, daemon and candidate-dependent work before changing transport or installer behavior. |
| Source evaluation | Requires measurement | Preserve the earlier rejected paired-evaluation trial and identify another concrete avoidable component before adding evaluator concurrency. |
| Release-packet origin receipt | Deferred adoption | Prior correct samples failed the warm cost gate; retain production ZIP verification. |
| Installer zstd preset | Deferred adoption | Existing diagnostics are not five eligible warm pairs plus a cold pair. Keep the stopped plan and failed costs; no automatic replacement samples. |

The helper observations preserve command output, exit codes, initializer
invocation/order, inherited configuration and guest resources. They introduce
no installer or guest behavior change. This cohort must be accounted separately
when it rolls out; no net savings is claimed before native results are measured.

Recent evidence is sufficient to advance these actions without waiting for
October 30. The original seven-day endpoint remains `2026-10-30T05:01:17Z` for a
separate complete-window assessment. Automatic Cachix writing and Grype database
transport remain disabled. Approval, fresh security, signing, reservation and
publication checks remain independent.
