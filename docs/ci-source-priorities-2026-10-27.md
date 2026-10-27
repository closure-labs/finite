# Source priorities and completed audit rollout, October 27 UTC

[#288](https://github.com/closure-labs/finite/pull/288) merged at
`25744e3562387c4febef32d7d8ef36a387c7c31a`. Its
[PR](https://github.com/closure-labs/finite/actions/runs/40442888362),
[queue](https://github.com/closure-labs/finite/actions/runs/40443714723) and
[main](https://github.com/closure-labs/finite/actions/runs/40444417610) passed,
using 431, 441 and 150 native runner seconds respectively. These are complete
Build Finite job totals, not workflow latency or all callback costs. Main CodeQL,
delivery health, decision reconciliation and cache maintenance also passed.
The [compressed evidence](ci-source-priorities-2026-10-27.json.gz) retains the
native accounting and source breakdown; grouped and native totals agree.

## Diagnostics and proof reuse

The queue authenticated `/nix/store/ck83xfh27bplzm09mp3i300p78gfy4an-finite-ci-checks.drv`.
Both evaluation and build succeeded on their first attempts. Main authenticated
that exact queue proof in 2.675 seconds, with no consumer evaluation/build phases.
The immutable main source artifact is 12707727176; its verified producer is
queue run 40443714723, artifact 12707119465. This demonstrates successful rollout
and normal proof reuse, not natural execution of the new transport retry.

The earlier #287 queue failed on interrupted NAR transfer and resumed HTTP 416;
its normal protected retry passed at the unchanged approved head. Preserve the
failed 346 runner seconds beside the successful queue's 439 and main's 134.
The bounded remediation shipped in #288 requires a prior interruption of each
exact resumed URL, within the same attempt; integrity, permission, evaluation,
builder, signal and resource failures remain terminal.

Neither recent main selected images. No production upgrade ran and no predecessor
diagnostic was expected. The last retained image-producing main predates #286.
Do not classify absent diagnostics as misses, infer a generation-context cause,
or claim production execution of #285's relocated preflight. Observe the next
ordinary production upgrade; no extra VM round was dispatched for this report.

## Source cost decomposition

This is a new analysis of the unchanged
[six-hour census](ci-recent-census-2026-10-27.md), not a newly selected cohort.
It retains failed work, separate revisions, native step rounding and unassigned
job intervals. Native pre-start intervals cannot be split into dependency wait
and runner queueing without authenticated dependency readiness.

| Work / native runner seconds | PR, five jobs | Queue, four jobs | Main proof consumers, four jobs |
| --- | ---: | ---: | ---: |
| Complete source jobs | 2,011 | 1,499 | 283 |
| Aggregate execution or proof lookup step | 1,699 | 1,262 | 10 |
| Nix setup step | 201 | 170 | 159 |
| Image selection step | 26 | 23 | 44 |
| Post-job work | 12 | 6 | 30 |
| Runner/checkout, retention and unassigned intervals | 73 | 38 | 40 |

PR and queue aggregate steps account for 2,961 of 3,510 source runner seconds,
about 84 percent. Seven authenticated evaluation receipts have a median elapsed
time of 263.116 seconds and median waited-child CPU/elapsed ratio of 2.231.
These counters exclude daemon work. They show substantial evaluator CPU use;
they do not identify a removable proof, establish a causal speedup or prove
absence of I/O waits. Receipt stages are nested within native steps and must
not be added to runner occupancy.

This ranks aggregate evaluation ahead of further post-job/cache-cleanup changes.
Do not repeat the [rejected proof scheduling experiment](ci-home-proof-evaluation.md)
without a materially different design. Preserve the complete strict Home Manager
proof matrix and aggregate identities. Main's setup is a larger fraction after
successful reuse, but moving lookup before Nix installation would lose the
current actual-client/configuration cohort check; no such shortcut is adopted.

## Foundation instrumentation and remaining work

[Foundation draft #23](https://github.com/closure-labs/foundation/pull/23) adds
opt-in timing observations at source `d7b10570c0123bac40f0bb56a9641db00f4cd477`.
It measures existing profile validation, Home Manager realization, Brew policy
evaluation/bootstrap, activation and rollback boundaries, including failures.
It preserves resource budgets, command arguments, configuration and one
initialization/activation. Finite remains pinned to published Foundation v0.3.3.

Realization's internal evaluation/fetch/build intervals and Flatpak work within
activation remain unknown. This first draft does not satisfy the entire O4
breakdown or authorize guest optimization. Review and publish Foundation before
an explicit Finite pin update and both profiles' fresh/upgrade/rollback acceptance.
Hosted Foundation CI is running; 46 guarded offline initializer tests and 11
download-recovery tests pass. An earlier broad discovery passed 184 tests but
also invoked small pure local Nix evaluations; it was not repeated. No local
Nix build or VM was run. Subsequent local checks explicitly block Nix commands.

Installer runtime reuse still lacks a candidate-independent boundary and complete
signed runtime identity. Compression remains deferred pending comparable cohorts;
controller reads remain serial after the zero-sample campaign. Publishing retains
the PAT; organization grant/scopes/expiry verification remains open. The
[release ledger](v0.8.3-release-plan.md) retains the final audit, stable qualification,
workstation pilot and immutable paired-proposal requirements. The original
October 30 complete-window assessment remains separate from this recent analysis.
