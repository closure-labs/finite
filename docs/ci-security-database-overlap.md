# Validate earlier security database acquisition

This is an **opt-in experiment**, not a production rollout. No workflow enables
it. Default scanning remains serial. Run
`python3 tests/bluebuild/security-database-overlap.py` for small offline lifecycle
fixtures; no OS image, real database, signing key or VM is needed.

## Why test this

The native receipts from [run 40704887511](https://github.com/closure-labs/finite/actions/runs/40704887511)
at source `29ff94251593c51eb08c4fef11a1fad15f69ea25` report DB acquisition of
71.230 seconds for finite and 56.181 seconds for finite-dev, after inventory.
Those are possible overlap windows, **not demonstrated savings**. Network, disk,
CPU and memory contention could erase the benefit or make the experiment slower.

## Safety boundary

On a provisioned GitHub-hosted runner with the pinned release tools, the existing
bounded launcher accepts an explicit opt-in:

```bash
bash scripts/bluebuild/security-run.sh "$immutable_image" "$new_evidence_directory" \
  --experimental-database-overlap
```

The launcher remains hosted-only and retains its shared `MemoryMax`, no swap,
OOM-stop policy, restricted capabilities and service cleanup. The extra updater
is in that same cgroup, not outside or in addition to its memory budget. The
Python opt-in also requires the launcher's bounded-service marker; that marker
is an invocation guard, not a security boundary against a hostile caller.

The experiment starts after immutable identity/baseline validation and before
inventory materialization or authenticated inventory copying. It uses one new
private, empty database directory; it neither restores nor modifies the shared
transport cache. There is at most one DB updater and one foreground inventory
command. Image copy parallelism and Syft workers remain one. Child output streams
without Python buffering; no extra image or rootfs copy is introduced.

The DB update has an independent 600-second deadline. Foreground commands retain
their 1,800-second timeout. Failures, timeout, SIGINT and SIGTERM terminate/reap
owned child process groups. A failed update is fatal even if an older shared DB
exists. Inventory failure cancels the updater. Cleanup joins the worker before
removing its cache, and the hosted service remains the final cgroup cleanup
boundary (including uncatchable kills).

The update must succeed before either Fedora coverage or vulnerability scanning.
Both use the same private cache with automatic updates disabled, hash and age
validation enabled, and no second update command. Existing native policy still
validates database build age, required provider freshness, Fedora RPM coverage,
SBOM/image binding and findings. An early acquisition that becomes stale before
policy evaluation **fails**, rather than refreshing between coverage and scan.
See [Grype configuration](https://oss.anchore.com/docs/reference/grype/configuration/)
for the supported database settings. No stale fallback or background error grants
clearance; the normal policy result is still required.

## Hosted experiment needed before any rollout

1. Use the same immutable image, pinned tools/policy, runner class and inventory
   mode for serial and overlap arms. Compare finite and finite-dev separately.
2. Give the serial arm a new empty `GRYPE_DB_CACHE_DIR` too. The overlap arm is
   deliberately cold; comparing it to a restored shared cache would confound the
   result. A warm-transport-cache experiment is separate future work.
3. Repeat both execution orders. Retain native security evidence, DB/provider
   identities and timestamps, phase timings, runner memory peak/OOM result,
   whole-job wall time, disk high-water usage and I/O/network contention metrics.
   Confirm matching snapshot identities when comparing findings; a DB publication
   between arms is a different cohort, not evidence of scanner equivalence.
4. Require healthy native policy and unchanged coverage in every accepted arm,
   no orphaned processes or cache contamination, no OOM or timeout regression,
   and a repeatable whole-job benefit within the existing resource budget.
5. Stop on safety failure or resource regression. Do not enable production from
   these fixture tests or from the original theoretical 56–71-second window.

`database-overlap.json` records update success and remaining wait after inventory;
it explicitly does not claim a performance improvement. In `phase-timings.json`,
the DB phase is marked `concurrentWithInventory`. **Do not sum overlapping phase
durations as wall time.** Metadata inspection, inventory lookup before the bounded
service, and final policy evaluation are not overlapped.

The existing policy-negative tests cover stale/invalid DBs, stale/missing provider
records and missing Fedora coverage. The new process fixtures cover real child
processes, both cancellation signals, timeouts, updater failure, inventory failure,
private-cache cleanup, single-snapshot ordering and unchanged default behavior.
Real Grype/database and shared-resource performance validation remain outstanding.
