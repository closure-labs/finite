# Decision staging rollout and controller timings, October 25 UTC

PR 256 merged as `4bdb26e403532b43f532ad8821a5dae1322c8e65`.
Its [protected queue](https://github.com/closure-labs/finite/actions/runs/40152796027)
and [main run](https://github.com/closure-labs/finite/actions/runs/40153237495)
passed, consuming 385 and 382 runner seconds respectively. Main selected no
images. The authenticated main aggregate was
`/nix/store/n1cr70mnk9ly6gc7xf79ws2f5hsb1nbi-finite-ci-checks.drv`.

The first natural
[reconciliation](https://github.com/closure-labs/finite/actions/runs/40153623404)
passed at that revision. Its native result selected no image work and reported
both profiles already dispatched to their completed recovery runs. Both profile
leaves still reference the same immutable packet. The reviewed implementation
therefore takes the staged-verification path for the second profile, preserving
native health and live approval checks. No diagnostic run was dispatched.

## Complete-job cost remains the decision measure

| Observation | Complete job seconds | Propose/reconcile step seconds | Nix setup seconds |
| --- | ---: | ---: | ---: |
| [Preceding natural run](https://github.com/closure-labs/finite/actions/runs/40149877163), before staging | 172 | 138 | 21 |
| First natural run with staging | 194 | 159 | 21 |

The [retained observation](ci-reconciliation-timings-2026-10-25.json.gz) binds
native run/job/source identities, unique-job accounting, structured controller
results and startup-log hashes. Its SHA-256 is
`1a828316ed52700d790014a623a5548699b8403607810e01249b22f503a68954`. Both startup headers identify
`20261012.334.1`; hardware, network and warmth were not controlled. One unmatched
observation establishes neither a causal regression nor recurring runner savings.
The eliminated 497,913,116-byte declared packet transfer is a transport effect,
not a demonstrated complete-job speedup. Earlier measurements remain preserved.

## Measure the work still inside reconciliation

Retain a small native observation for naturally occurring reconciliations:

- Packet download and staged manifest/inventory/hash verification separately.
- Native evidence evaluation and each live authority check.
- Producer-input resolution, journal reads/writes and dispatch discovery.
- Publisher-busy checks, current-source validation and dispatch itself.
- Staging cleanup and the outer reconciliation interval.

Rows identify profile, start time, elapsed seconds and call outcome. Successful
completion of an observed call does not establish approval or publication
eligibility. Function arguments, return values, findings and credentials are not
recorded. The outer interval contains the child phases; do not add their times.
Earlier proposal collection and Nix environment preparation remain outside the
Python reconciliation interval and stay charged in native step/job occupancy.

The observer writes a running row before a call, then its completion or error.
Unavailable/reset clocks remain unknown, including when the command succeeds.
Recording failures preserve the original operation result or exception. At most
64 rows and 64 KiB are retained, with truncation explicit. Actual checkout SHA
is recorded separately from native run revision; unavailable checkout identity
stays unknown. The failure-safe upload retains only this JSON for 14 days.

The read-only cost collector authenticates the bounded Actions ZIP and exact
repository/workflow/run/source/attempt/job binding. It preserves partial rows,
per-profile detail and native retry accounting without charging a reused job
twice. Invalid or conflicting receipts are rejected. Missing observations do not
become zero cost or inferred cache misses. Upload, retention and cleanup costs
remain part of the complete native job and need rollout measurement themselves.

No security, dispatch, installer or guest behavior changes here. Release-product
ZIP verification, controlled benchmark gates, the stopped installer plan,
disabled automatic Cachix writing and disabled Grype database transport remain
unchanged. Collect recent natural evidence without waiting for October 30 or
adding full VM rounds solely for a report.
