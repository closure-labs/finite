# Source resource observations and recent results, October 25 UTC

PR 262 merged as `54b5661fe3a0664f4984d4fc7ee339de70420f87`.
Its [protected queue](https://github.com/closure-labs/finite/actions/runs/40201749164)
and [main run](https://github.com/closure-labs/finite/actions/runs/40202322567)
passed and selected no images. Both authenticated source receipts identify
`/nix/store/k9gry9i8z5mhqlrgsizy1wwy7fzxzmd0-finite-ci-checks.drv`.
The two natural controllers at this revision also passed. No diagnostic workflow
was dispatched to obtain these observations.

## Measured costs determine the next work

The following scoped samples rank native runner occupancy. They cover different
events and source revisions, not a common fleet observation window. Frequency
means observed jobs in this sample, not an estimated daily rate. Sole-runner
occupancy is a lower bound on blocking within its own workflow; exact dependency
DAG contributions remain unknown.

| Work and scope | Observed jobs | Known runner seconds | Known sole-runner seconds |
| --- | ---: | ---: | ---: |
| Fresh and upgrade/rollback qualification, security-259 recoveries | 4 | 6,259 | Unknown in this projection |
| Source contracts, 262 queue and main | 2 | 782 | 782 |
| Decision reconciliation, two natural controllers after 262 | 2 | 391 | 391 |

The four qualification jobs come from the successful
[finite](https://github.com/closure-labs/finite/actions/runs/40168352161) and
[finite-dev](https://github.com/closure-labs/finite/actions/runs/40171167682)
recoveries at `3701168749724d97da53fc825bec0035eb6a4f7b`. Their authenticated
host/guest joins have no unmatched receipts. Inside those jobs, VM acceptance
totals 4,047.219 seconds; two fresh ISO builds total 1,314.761 seconds. The four
guest `home-init` intervals total 1,643 seconds. These are nested measurements,
not costs to add to job occupancy or each other. Initialization still combines
evaluation, transport and activation. Whole-second guest zeros do not establish
that startup, Homebrew or predecessor work was absent. ISO waited-child CPU
excludes independent container-daemon work.

| Source run | Complete source job seconds | Evaluation seconds | Build seconds | Store snapshot hit |
| --- | ---: | ---: | ---: | --- |
| 262 queue | 378 | 268.280 | 55.588 | Yes |
| 262 main | 404 | 273.936 | 71.248 | Yes |

The phases total 669.052 seconds inside 782 source-job seconds. Evaluation alone
totals 542.216 seconds. These repeated costs do not establish avoidable work or
reuse eligibility. The restored store snapshot does not establish an evaluation
cache hit: the current setup action explicitly retains the store and download
caches, with no evaluation-cache path. Changing the resolver alone has no
demonstrated complete-job benefit. Preserve the rejected parallel Home Manager
evaluation trial and serial evaluator/build ordering.

The main selection job took 51 seconds, including a 21-second channel step.
The [earlier baseline](ci-channel-payload-2026-10-25.md) was 59/25 and 50/21
seconds respectively. Sharing the payload evaluation executed successfully, but
one unmatched main observation does not establish a complete-job speedup.

The natural [scheduled controller](https://github.com/closure-labs/finite/actions/runs/40202762001)
used 181 runner seconds and the
[completion controller](https://github.com/closure-labs/finite/actions/runs/40202948602)
used 210. Four live authority checks account for 199.102 nested seconds. Each
controller downloaded the packet once; second-profile staged verification took
0.632 and 0.737 seconds. No publisher-busy call executed in these receipts, so
they do not measure the active-lookup optimization. Live authority checks remain
independent; timing alone is no reason to cache an approval decision.

## Add CPU and I/O observations to existing source attempts

The source wrapper now records `childResourceUsage` alongside each attempt's
wall time and status. It subtracts `RUSAGE_CHILDREN` user/system CPU and block
operation counters before and after the serial command is reaped. Failed
attempts retain their observations; transport retries get separate deltas and
retry sleep remains outside attempt counters. Unavailable/reset counters and
unlaunched commands retain null observations. A measured zero stays zero.

The scope matches the existing host timing vocabulary:
`terminated-and-waited-children`, with `includesDaemonWork: false`. Independent
Nix/container daemons, unrelated runner processes and detached work are outside
this scope. Block operations are not bytes. CPU seconds do not identify a
particular expression, network wait or guest activation. Lifetime maximum RSS
cannot be subtracted into a per-attempt maximum, so no such measurement is
reported. These observations await natural hosted evidence.

The bounded collector accepts legacy receipts without the optional field and
validates new resource types, limits and scope before retaining them. Resource
counters remain nested in their originating attempt. They are never charged as
additional runner seconds. Required aggregate evaluation/build commands, retry
classification, lock flags, successful GC roots and phase ordering are unchanged.

## Current work list

| Work | Classification | Next action |
| --- | --- | --- |
| Single channel payload evaluation | Completed; savings require measurement | Follow natural complete selection jobs. |
| Source CPU and block operations | Awaiting rollout evidence | Use existing source jobs to distinguish compute cost from unexplained wall time. |
| Source resolver/cache or exact-source proof reuse | Requires design and measurement | Establish cache availability, provenance and complete-job benefit; preserve all required checks. |
| Guest initialization and ISO runtime | Requires measurement | Isolate avoidable work before changing transport, installer behavior or guest resources. |
| Packet staging and active publisher lookup | Completed; whole-job savings require measurement | Preserve per-profile integrity and live checks; wait for naturally executed lookup paths. |
| Product-origin receipt, zstd and same-build OCI export | Deferred | Preserve failed/stopped samples and existing correctness/performance gates. |

The [frozen evidence](ci-source-resources-2026-10-25.json.gz) retains native
job costs, authenticated source proofs, controller projections and guest joins.
Its SHA-256 is
`f246233f7449120d0be7f38b4616013e252ea54925659c5cf268443ac2b57035`.
Historical reports remain unchanged. The October 30 endpoint remains separate;
recent runs support continued work now. No local Nix, image or VM run was used.
Automatic Cachix writing and Grype database transport stay disabled. Approval,
security freshness, signing, reservations and publication checks are unchanged.
