# Bounded delivery-health history

The monitor previously inspected only 30 main builds. Source-only green builds
could displace the last image promotion without indicating a publication failure.
It now reads up to five pages of 30 native Build Finite runs, retaining both
active and completed trusted-main runs. The report records whether available
history was exhausted or the 150-run discovery limit was reached.

Qualification and promotion timestamps come from their successful native jobs,
not the workflow's mutable `updated_at`. The monitor compares completion times
across the bounded inventory: an older-created run can promote more recently on
retry. Creation time is therefore not a safe freshness cutoff. The existing
36-hour freshness threshold remains unchanged, including its exact boundary.

Missing promotion evidence is explicitly unavailable or absent from the observed
history, not proof that publication failed. Actual latest-build failures, active
failed phases, partial channel state, authenticated release-publisher failures,
and informational approval waits retain their independent meanings. Source CI
success still does not establish that a new image or release was published.

Discovery and job/artifact reads have a 120-second admission/result budget.
Individual GETs keep their existing bounded transport timeout and retries; an
in-flight request is not forcibly interrupted, but a result arriving after the
budget cannot produce a healthy snapshot. Missing timestamps, incomplete job or
artifact inventories, duplicated pagination identities, unavailable metadata and
expired observation budgets fail closed. Failed inspection still removes stale
same-job snapshots; audit reporting remains independent. No publication,
approval, preparation-dispatch, signing or reservation policy changes.

Offline regression coverage includes more than 30 source-only builds, both
channels and partial channels, the freshness boundary, older-run retries,
mutable workflow metadata, absent/capped history, missing timestamps, unavailable
pages, duplicate runs, incomplete inventories and deadline crossing. Existing
publisher, snapshot, reconciliation and independent-failure checks remain in the
normal hosted aggregate. No image build, VM or hardware test is needed for these
metadata-only regressions. Hosted exact-head CI remains the adoption check.

## Bounded read concurrency correction

The first natural rollout exposed the serial-read cost. In
[health run 40822125625](https://github.com/closure-labs/finite/actions/runs/40822125625),
inspection started at `05:14:03.435760Z` and raised the budget error at
`05:16:04.366095Z` on October 29 (120.930 seconds). The next
[health run 40822345179](https://github.com/closure-labs/finite/actions/runs/40822345179)
started inspection at `05:16:50.519718Z` and raised at `05:18:52.292259Z`
(121.773 seconds). The latter logged an HTTP 502 and one retry while reading
run 39910736417's attempt-1 jobs. Historical successful GETs were not logged,
so exact request counts and per-request durations cannot be reconstructed.

The correction keeps the 150-run discovery limit and 120-second budget, and
reads job inventories in batches of at most four concurrent requests. A failed
batch prevents submission of later batches. Each batch is shape-validated before
processing and streamed without retaining the full 150-run response set. At
most one batch plus the consumer's prior response remains live. Every read checks the shared
budget before admission and after its response. In-flight requests retain the
existing bounded transport retries; they are not forcibly cancelled. No late
result can produce a snapshot, and full inventory/identity checks remain.
All discovered runs still contribute to older-run retry ordering; no creation-
or update-time heuristic weakens evidence coverage. Preparation and independent
audit behavior remain unchanged.

A metadata-only observation line records admitted (`readCalls`)/completed/failed logical read counts,
peak concurrency, summed read duration and wall span, including failures. It
contains no endpoint queries, response bodies or credentials. Summed durations
overlap under concurrency and must not be added to wall time. These counters
include discovery and preparation-eligibility artifact reads, not subsequent
release/publisher inspection or individual internal transport retry attempts.

Offline regressions demonstrate four-way execution, no additional batches after
failure or malformed inventory, bounded response retention, unchanged deadline
rejection and failure telemetry. This is not a
measured hosted latency improvement: observe ordinary health runs after any
separately reviewed adoption. Neither failed natural run was rerun for a sample.


## Current-main refresh

The same failure persists on `cf2d25d5dd56b49e3d9dd6c6b3853756f71c83a4`:
[health run 40974124822](https://github.com/closure-labs/finite/actions/runs/40974124822)
started inspection on October 29 at `23:35:43.203742Z` and raised the budget
error at `23:37:44.734490Z` (121.531 seconds). No retry warning appeared in
that log. The same-job snapshot was absent, preparation was skipped, the
independent audit succeeded, and the final health job correctly failed.

The refresh preserves the current main tree outside these health changes.
Additional offline cases exercise the actual transport with mocked subprocesses:
exhausted timeouts, a rate limit requiring a wait beyond its budget, recovery
from a short rate limit, and malformed/partial job responses. These tests do
not issue live requests, relax security policy or turn missing evidence healthy.


## Bounded rolling-window correction

After the first correction, [run 41002497896](https://github.com/closure-labs/finite/actions/runs/41002497896)
still exhausted the observation budget: 150 logical reads were admitted, 146
completed and four failed, with peak concurrency four, 121.575 seconds of
observed wall span and 256.7 summed read seconds. The traceback establishes a
late-result rejection. These aggregates do not establish the individual cause
of every failed read or attribute the delay to a particular request.

The scheduler now refills on completed reads rather than waiting at a four-read
batch barrier. It preserves input run order, allows at most eight admitted but
unconsumed inventories, and applies backpressure when an older slow read fills
that reorder window. The consumer may retain its previous response separately.
Every completed future observed in a scheduling pass is validated before any
replacement is submitted. A shared four-slot semaphore also covers foreground
artifact reads, so prefetch cannot raise global read concurrency above four.
Slot admission and returned results both retain the 120-second deadline; the
150-run discovery limit, native-attempt evidence and all health failures remain.
There is no cache, timeout increase or publication/approval policy change.

Additive telemetry records `maxReadSeconds`, admitted-read `failureReasons`
(`readError` or `resultDeadline`), and `admissionRejections` for reads never
admitted. Inventory-shape errors occur after a successful metadata read and are
not transport failures. Counters expose no endpoint, response or credential.

Event-controlled offline fixtures demonstrate that run five can start while
run one is blocked, ordered consumption despite reversed completion, bounded
reorder retention, out-of-order malformed-result rejection, global concurrency
including artifacts, and slot/result deadline failures. This proves scheduler
behavior, not a hosted latency improvement or guaranteed completion within the
budget. Ordinary exact-head CI and natural health observations remain necessary.
