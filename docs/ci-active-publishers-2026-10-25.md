# Active publisher lookup, October 25 UTC

PR 257 merged as `70a8c15e73a58279bc91a55d32b97210337e945d` after its
[protected queue](https://github.com/closure-labs/finite/actions/runs/40166965246)
passed. Security decision 259 then merged as
`3701168749724d97da53fc825bec0035eb6a4f7b` after exact-head human approval and
its [queue checks](https://github.com/closure-labs/finite/actions/runs/40167523769).
The automatic main publishers were stopped before image or VM work so the
native decision controller could recover the original retained candidates.
The exact merged revisions already passed their pinned source aggregates.

## First natural controller phase receipt

The [native reconciliation](https://github.com/closure-labs/finite/actions/runs/40168197723)
succeeded and dispatched `finite` recovery from original producer `40162236269`.
Its authenticated compact receipt binds repository, workflow, run, attempt,
source, actual checkout and producing job. Complete native job occupancy was
164 seconds; the reconciliation interval was 114.036 seconds.

| Reconciliation work | Seconds |
| --- | ---: |
| Initial live authority check | 34.361 |
| Independent authority recheck before dispatch | 32.267 |
| Packet download and verification | 16.465 |
| Initial publisher-busy lookup | 10.722 |
| Publisher-busy recheck before dispatch | 12.297 |

These are child phases inside the outer interval. Do not add either the interval
or its children to native job occupancy. Setup, retention and other work remain
charged in the complete job. This invocation dispatched the first profile and
stopped; it does not measure second-profile staged verification or establish a
matched speedup for packet staging. The earlier cancelled-producer controller
failed before timing initialization: its 56 seconds remain charged, with phase
coverage missing rather than zero.

The [frozen evidence](ci-active-publishers-2026-10-25.json.gz) has SHA-256
`e7cef0fb3811cfe2bb70756184ba0b9f41c25c478a1e0dcda724bedb59f2b818`.
It preserves complete native cost, every recorded phase, and the separate
read-only API comparison below. Historical reports retain their original data.

## Query incomplete runs directly

The two busy checks spent 23.019 seconds enumerating completed history as well
as active runs. Query each incomplete status separately, using the existing
bounded collection reader. GitHub's
[workflow-run API](https://docs.github.com/en/rest/actions/workflow-runs?apiVersion=2022-11-28#list-workflow-runs)
supports status filters for in-progress, queued, requested, waiting and pending
runs. This is also the status set already used by upstream channel recovery.

Keep the repository, workflow, branch, event and incomplete-result predicates.
Keep both fresh checks around the journal claim and dispatch. No response is
cached or reused between checks. A transport, malformed collection or pagination
failure propagates; none means the publisher is idle. Completed history cannot
consume the active-query pagination bound or hide an older waiting publisher.

A read-only comparison invoked only the old and proposed busy predicates in two
predeclared opposite orders while the production recovery was active. A GET-only
wrapper and read-only App token prevented mutations. Both methods returned busy
in both pairs:

| Pair | Existing history lookup seconds / requests | Active-status lookup seconds / requests |
| --- | ---: | ---: |
| 1, existing first | 10.760 / 5 | 0.468 / 1 |
| 2, prototype first | 9.861 / 5 | 0.456 / 1 |

These are API-function observations, not matched hosted complete-job samples.
An idle check queries all five statuses and may use more requests than a small
history listing. No complete-job savings is established. Keep the change draft
while both profiles' retained-image qualification and promotion are active;
collect native job and phase evidence after any eventual rollout.

## Current work list

| Work | Classification | Next action |
| --- | --- | --- |
| Bounded controller timings | Completed rollout | Retain natural receipts, including failures and missing coverage. |
| Active publisher query | Draft prototype; awaiting rollout evidence | Focused regressions and the hosted pinned aggregate must pass. Measure actual job cost after rollout. |
| Shared packet staging | Awaiting savings evidence | Second-profile observations are still needed; the first-profile receipt is not a staging comparison. |
| Repeated full recovery while security is pending | Requires design | Authenticate candidate identity and retained evidence before suppressing work; any open PR alone is insufficient. Three stopped automatic publishers used 466 runner seconds before image/VM work. |
| Repeated source contracts | Requires measurement/design | Use exact native source/aggregate proof. The two new queue aggregates differ; do not infer cross-revision eligibility. |
| Installer runtime or guest transport | Requires measurement | Preserve existing fresh install, actual bootc Home Manager activation and all security/upgrade/rollback acceptance. |
| Release-product origin receipt | Deferred adoption | Prior warm cost gate failed; retain production ZIP verification. |
| Installer zstd and local OCI alternatives | Deferred | Preserve stopped samples and cohort gates; no usable same-build dual export exists in the locked CLI path. |

Independent approval, security freshness, signing, reservation and publication
checks retain their behavior. No installer or guest behavior changes. Automatic
Cachix writing and Grype database transport stay disabled. No local Nix, image or
VM run, or extra controller run for measurement, was performed. Recent evidence
is actionable without waiting for the separate original October 30 endpoint.
