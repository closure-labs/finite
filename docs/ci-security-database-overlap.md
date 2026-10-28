# Validate earlier security database acquisition

This is an **opt-in experiment**, not a production rollout. Production scanning
remains serial. The manual `benchmark-database-overlap.yml` workflow compares
the two paths in isolation; it cannot build, sign, promote or release an image. Run
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

## Manual hosted comparison

After the benchmark workflow is reviewed and available on `main`, dispatch
**Benchmark isolated security database overlap** with:

- `image`: the complete immutable `ghcr.io/closure-labs/finite@sha256:...` reference;
- `profile`: `finite` or `finite-dev`, tested in separate workflow runs;
- `origin_run`: the successful native main **Build Finite** run that produced
  this exact signed image and its native security evidence.

The benchmark authenticates the native producer metadata and signature before
scanning. It requires an explicit manual main invocation in `closure-labs/finite`
and read-only credentials. It does not accept a mutable image tag, a failed
producer, or a locally fabricated hosted event.

Six fresh `ubuntu-24.04` jobs each run a serial/overlap pair sequentially: three
serial-first and three overlap-first repetitions. At most one pair job runs at a
time. A failed pair stops the remaining matrix jobs. Each arm uses fresh image
inventory and a cold isolated DB; no scanner or inventory cache is restored or
saved. Public pinned Nix tool substitution is common to both arms and is not a
scanner-cache hit. Paired arms share setup, and the second arm may benefit from
host or network caches outside the experiment's control. Reversed orders expose
that effect; they do not establish a perfectly cold host cache.

The benchmark owns its bounded hosted scanner service and calls the same native
scanner with the overlap CLI flag only in the overlap arm. This does not change
the production launcher or enable a production feature flag. The paired arms
must use matching immutable image, source, tool, policy and runner identities,
and matching resource controls. Both run the native policy without a waiver.
Each scanner shares a fixed 10-GiB cgroup limit with its updater, reserves 4 GiB
of available host RAM, allows no swap, and has a 3,600-second scan deadline
plus 180 seconds for bounded evidence validation. The service limits tasks to
256 and stops on OOM; a sampled 4-GiB free-disk floor is enforced. Native DB
command deadlines remain 1,800 seconds for serial and 600 for overlap.
Both arms enable database hash and age validation at startup.

Scanner-reported DB/provider snapshot identity must match before comparing
findings or timing: schema, build time, source and every provider capture/input
identity are retained; only the arm-owned database path is normalized. This is
not an independently hashed database-file comparison.
An upstream DB publication between arms, changed coverage, unhealthy scanner,
OOM, timeout, incomplete telemetry or missing observation rejects the comparison;
it is not counted as a performance gain. The summary explicitly rejects incomplete cohorts; available individual failure
receipts remain in artifacts rather than silently becoming accepted samples.

Artifacts retain bounded native policy/provenance/timing evidence, resource
measurements, integrity hashes for full evidence files, and complete same-attempt
GitHub job timestamps. Image layers, extracted rootfs, raw DB and unbounded full
inventory payloads are not uploaded. Arm wall time is measured directly: never
sum overlapping phase durations. Whole-job timestamps describe the complete
**pair job**, including common setup and both arms; they are not independent
serial-versus-overlap whole-job measurements. Even a repeatable arm-level benefit
therefore remains diagnostic rather than sufficient production rollout evidence.

The per-pair job timeout is 120 minutes and artifacts expire after 14 days. The
workflow stops instead of refreshing or substituting a DB merely to make a
cohort comparable. Rerun only after diagnosing a rejected cohort; do not mix
receipts across workflow attempts.

## Evidence needed before any rollout

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
The hosted benchmark is a way to collect real Grype/database and shared-resource
performance evidence, not evidence that those runs have already passed.
