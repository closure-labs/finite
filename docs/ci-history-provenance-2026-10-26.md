# Historical decision provenance read prototype

Status: prototype, serial by default. Do not enable parallel production reads
until hosted checks and a complete-job canary pass. This work follows the
[0.8.3 ledger](v0.8.3-release-plan.md), investigation O2.

## Observed work

The natural [#277 reconciliation](https://github.com/closure-labs/finite/actions/runs/40359152147)
used 219 native runner seconds. Its authenticated receipt measures 158.216
seconds in reconciliation, including 32.093 in packet download and 112.794
across the two profiles' authority checks. Nested stages are already inside
the job. There are eight security records, with seven historical ancestors
requiring provenance and one current decision requiring live human authority.

The [frozen record](ci-history-provenance-2026-10-26.json.gz) has SHA-256
`0943fed01ebd3ae9ad82e624619cacc612c94d01097957b3016f5c35aab95ccf`.
It retains the native projection, preregistered replay and all six samples.
Native job cost remains 219 seconds; a local API replay cannot restate that cost.

## Bounded read-only replay

The frozen campaign binds its recorded main revision
`e0b270e0b1c416fb3944193730ee0f3c0b46c19e`, all seven proposal hashes and the
prototype file hashes. It runs serial/four-worker arms in order
`1,4,4,1,1,4`, with a new immutable-document scope per arm. It allows at most
1,000 logical GET calls and 900 seconds. Each arm checks that main and the
prototype remain unchanged. GitHub service temperature is uncontrolled.

Every arm performed 70 logical reads and returned the same provenance receipt
hash. The active decision was excluded: no current acceptance authority,
publication, status check, dispatch, Nix build or VM run was issued. The token
requested only repository contents and PR read permissions and was revoked
after the comparison. Including initial/final inventory checks, the campaign
made 424 logical reads and took 191.087 seconds.

| Three-sample median | Seconds |
| --- | ---: |
| Serial historical reads | 48.592 |
| Four historical read workers | 13.750 |
| Observed difference | 34.842 |

This passes the preregistered replay gate: identical receipts, no additional
logical reads, and at least 10 percent and 10 seconds lower median. It does not
establish hosted job savings or authorize deployment.

## Implementation and canary boundary

Validate the entire local decision graph before starting history reads. At most
four workers then independently authenticate historical PR origin, merged bytes
and main ancestry. They never cache a current approval, role or membership.
The active decision's full live verification runs sequentially after every
ancestor succeeds. The final pre-dispatch authority recheck remains serial.
Any history error cancels pending reads and prevents current acceptance.

Context propagation shares only the existing bounded authenticated immutable
document cache. A lock preserves its 64-entry/16 MiB budget under concurrent
misses, charges a binding once and rejects conflicting immutable bytes. There
is no cross-invocation cache. Main's complete decision inventory is still checked
before and after admission; revocation and changed-ledger regressions remain.

The controller CLI accepts `--historical-read-workers 1|4`, defaulting to one.
Only its initial read phase can use four workers through the nonsecret
`FINITE_AUTHORITY_HISTORY_WORKERS` repository variable; the final mutation guard
does not use that setting. Native timing receipts record the selected count.
Legacy receipts keep the count unknown. Cost attribution recognizes `reconcile`
only within its authenticated native workflow and conserves unique job cost.

The prototype is rebased onto merged #283 at
`774c3ebab68ce1ec29ff97e66eddafb48a57fdc3`. Its source tests can run while
main qualification proceeds, but keep it draft and out of the queue until
that production rollout succeeds. Require hosted pinned aggregate checks. Then observe one natural four-worker controller with the same ledger,
packet and declared tool cohort, keeping all guards enabled. Compare complete
job occupancy, setup, transfers, lookup, retention and cleanup against the
serial cohort; do not substitute replay timings. Return the setting to one
after the trial, or immediately on correctness failure. Promote only after
correctness and lower complete-job cost are demonstrated.

## Already integrated retry accounting

The parent rollout #283 already contains this accounting repair. This prototype
retains that implementation and does not reimplement it.

The natural failed-jobs recovery of main run `40367978697` assigned a new
check-run ID to a previously completed source job: `121731361655` became
`121779545701`. Both identify runner `1000020488` and the same 56-second
execution, ending before attempt two started. Counting native IDs alone would
charge it twice. The report now recognizes a copied completed execution only
when source, name, runner, interval, outcome and every native step match a
single earlier attempt, and completion precedes the new attempt's start.
It retains the original job/receipt binding plus the new ID as an alias.
Missing or differing evidence preserves separate observations; actual retries
and failed work remain charged. This corrects accounting, not CI runtime.
