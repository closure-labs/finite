# Immutable decision documents and rollout, October 25 UTC

PR 263 merged as `800a4d997c23549ae36c27350ee63cba0a4c6685`.
Its [queue](https://github.com/closure-labs/finite/actions/runs/40208194553)
and [main](https://github.com/closure-labs/finite/actions/runs/40208766621)
passed, consuming 417 and 409 known runner seconds. Both selected no images.
CodeQL and the natural
[decision controller](https://github.com/closure-labs/finite/actions/runs/40209276310)
also passed. These unmatched observations do not establish complete-job savings.

## Source measurements now distinguish client CPU

| Source job | Native runner seconds | Evaluation wall seconds | Evaluation child CPU seconds | Build wall seconds |
| --- | ---: | ---: | ---: | ---: |
| Protected queue | 382 | 261.012 | 655.691 | 68.312 |
| Main | 320 | 217.848 | 547.753 | 53.029 |

The authenticated source receipts bind both jobs to the same aggregate,
`/nix/store/79m3wgx7vfbwc3pwlgkzhl4am74bmk6y-finite-ci-checks.drv`.
Evaluation averages approximately 2.5 observed CPU cores. That establishes
substantial computation in the waited-for processes, without identifying which
expressions are avoidable. Build client CPU was only 2.289 and 1.413 seconds;
independent Nix builders/daemons are excluded, so these figures do not establish
idle builds. CPU, wall time and job occupancy are different measurements and
must not be added. The two source jobs account for 702 native runner seconds and
702 measured sole-runner seconds within their workflows; exact DAG contribution
remains unknown. Required source checks still run in full.

## Remove repeated immutable document transfers

The controller used 141 runner seconds, including 66.874 nested seconds in two
independent authority checks. With eight security decisions in the current
ledger, each profile revisits the same reviewed, merged and current-commit
documents while validating the decision chain. The complete Git object at a
specified repository, path and immutable commit cannot change between profiles.

Retain verified raw document bytes inside one reconciliation invocation. First
fetches still require immutable-ref metadata, bounded regular-file content,
base64/size validation, Git blob identity and strict JSON parsing. Subsequent
lookups of that exact binding parse fresh objects from the retained immutable
bytes; callers still compare canonical proposal identities. A changed repository,
path, reviewed head or current-main commit requires a new binding and read.
Duplicate keys, nonfinite JSON, invalid hashes and failed reads never populate
the retained data.

This removes redundant immutable-content reads and repeated Git-object hashing.
It retains fresh PR state, reviews, current memberships, repository permissions,
main references, ancestry comparisons, ledger inventories and revocation checks.
Both per-profile admission checks and the independent check before dispatch
still execute. Native scan health, staged packet integrity, reservations,
publication checks and lost-response recovery remain independent.

The scope is bounded to 64 bindings and 16 MiB of raw bytes. Capacity exhaustion
falls back to the original reads. There is no disk cache or retained approval
result. Normal return and exceptions release the scope; the next reconciliation
starts with no retained documents. Other callers retain their original behavior.

## Read-only comparison and acceptance limits

Two alternating comparisons fetched the active proposal at its exact reviewed,
merged and current commits for both profiles. All canonical identities matched.
Setup, including the native PR and main-reference lookups, took 0.778 seconds
once and is reported separately.

| Pair | Existing document bundle seconds | Shared document bundle seconds | Existing/shared GET count |
| --- | ---: | ---: | --- |
| 1, existing first | 3.814 | 1.932 | 6 / 3 |
| 2, shared first | 4.420 | 2.809 | 6 / 3 |

Serialized response projections totaled 4,743,450 bytes per existing bundle and
2,371,725 per shared bundle. These are JSON projections, not wire-byte counters.
This diagnostic covers one active proposal's document reads, hashing and parsing;
it excludes complete controller setup, live authority checks and packet cleanup.
It establishes neither fleet frequency nor native complete-job savings. Observe
natural controllers after rollout; no Actions or VM rounds were dispatched for
this comparison.

Focused regressions preserve warm-document approval withdrawal, changed head or
main content, membership/permission loss, API failure, capacity fallback, invalid
bytes, nested scopes and failed-dispatch cleanup. Existing revocation, stale
source/security, reservation, ambiguous-response and partial-publication checks
remain required.

| Work | Classification | Next action |
| --- | --- | --- |
| Source CPU/I/O observations | Completed | Retain both native rollout receipts; preserve daemon exclusions. |
| Shared immutable decision documents | Awaiting rollout evidence | Compare naturally occurring complete controller costs and actual repeated reads. |
| Source resolver/cache or exact-source proof reuse | Requires measurement | Identify a validated avoidable component before changing required source execution. |
| Installer/runtime and product transport alternatives | Deferred | Retain the stopped samples, failed transport gate, default compression and production ZIP verification. |

The [frozen evidence](ci-immutable-documents-2026-10-25.json.gz) has SHA-256
`5fd2243f9fc9fbbc059b10fd30599a144034f2ed5d147ae048b3c402a7df3049`.
Historical reports and the October 30 endpoint remain separate. No local Nix,
image or VM run was used. Automatic Cachix writing and Grype database transport
stay disabled.
