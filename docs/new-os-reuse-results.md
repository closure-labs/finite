# Reuse measurements for the new Bluefin-based OS

Measured on October 15, 2026, using only the new upstream-preserving `finite`
and `finite-dev` images. No old replacement-kernel image or retired Next variant
was benchmarked in this comparison. All four final experiments passed; reuse
defaults remain unchanged.

## Qualified origin

[PR #172](https://github.com/closure-labs/finite/pull/172) merged through the
protected queue at `2816fa4d16706a60e6cb91c616493aeeb7432101`.
[Main producer 38777997975](https://github.com/closure-labs/finite/actions/runs/38777997975)
passed both builds, assembled-image preservation checks, fresh native security,
signatures, all four fresh-install and upgrade/rollback VM phases, desktop
acceptance, aggregation and promotion. Only the two active profiles were selected.

Both images retain Bluefin's kernel and modules together, including inherited
ZFS. Finite no longer directly removes those modules or replaces the kernel.
The preservation checks and VM results do not claim an independent ZFS pool
workload test. See [upstream foundations](upstream-kernel-variants.md).

## Whole-qualification reuse

Each experiment ran three independent restore jobs and three separate aggregate
jobs against the exact new candidate, predecessor, source, build identity and
qualification context. The production resolver, current preflight and receipt
validation ran on hosted runners. The original qualification timestamp and
24-hour deadline were preserved. Every sample passed.

| New variant | Original critical-path service time | Median restore + aggregate | Saved per eligible hit |
| --- | --- | --- | --- |
| finite | 32m44s | 2m15s | 30m29s (93.1%) |
| finite-dev | 34m34s | 2m13s | 32m21s (93.6%) |

Original critical-path service time is prepare + max(fresh, upgrade) + aggregate.
The reused path includes both complete jobs, including setup and post-job work.
Parallel VM jobs consume more total runner time than their elapsed critical path:

| New variant | Original summed runner time | Median reused runner time | Original elapsed, including gaps | Median reused elapsed, including gaps |
| --- | --- | --- | --- | --- |
| finite | 59m20s | 2m15s | 32m52s | 3m37s |
| finite-dev | 60m27s | 2m13s | 34m41s | 3m39s |

This compares one observed fresh production qualification per variant with three
eligible reuse pairs. It establishes substantial savings for an exact eligible
hit; it does not measure production hit rate or savings across changing images.
Fresh security is separate and remains mandatory. Diagnostic handoffs grant no
publication clearance. Do not multiply these per-hit savings by all daily builds.

## Inventory reuse

Three baseline/reuse pairs per variant authenticated the same signed new image
and native origin, started without DB transport, and performed fresh DB update,
coverage, vulnerability scanning and current policy evaluation. All six readers
within each variant matched tools, runner-image cohort, DB/provider snapshot,
inventory generation and semantic policy output. Every scan passed.

| New variant | Baseline complete-job median | Reused complete-job median | Median paired saving |
| --- | --- | --- | --- |
| finite | 8m51s | 2m26s | 6m55s (74.0%) |
| finite-dev | 16m19s | 2m56s | 13m30s (82.4%) |

Paired savings are calculated within each repetition, then take their own
median; they need not equal the difference of the two lane medians. For example,
standard baseline samples were 488/611/531 seconds, reused samples 146/159/116
seconds, and paired savings 342/452/415 seconds. All samples and exact timestamps
are in the linked JSON evidence. These are three hosted observations per variant,
not a large statistical trial or a promise for other runner hardware.

The phase receipts show the avoided work and the security work that remained:

| New variant | Avoided image transfer median | Avoided extraction median | Avoided cataloging median | Fresh DB update median with reuse | Fresh vulnerability scan median with reuse |
| --- | --- | --- | --- | --- | --- |
| finite | 69.3s | 129.0s | 167.8s | 67.8s | 20.1s |
| finite-dev | 180.7s | 282.5s | 310.5s | 85.2s | 36.1s |

Complete reader jobs include inventory download, authentication, tooling, setup
and cleanup costs. Fresh policy evaluation also ran in every reader. No DB seed
or transport ran. The one-off experiment report collector is outside the reader
jobs being compared; it is not part of the production per-hit security path.

## Evidence and credential integration

- finite: [inventory 38787802299](https://github.com/closure-labs/finite/actions/runs/38787802299), [qualification 38793866627](https://github.com/closure-labs/finite/actions/runs/38793866627).
- finite-dev: [inventory 38787811046](https://github.com/closure-labs/finite/actions/runs/38787811046), [qualification 38793870423](https://github.com/closure-labs/finite/actions/runs/38793870423).

Small summary archives were authenticated by repository, run, attempt, source,
artifact ID, size and SHA-256. Medians were independently recomputed from the
authenticated job timestamps. [Machine-readable evidence](new-os-reuse-results-2026-10-15.json)
records candidate/predecessor digests, build identities, original jobs, summary
artifact digests, matched cohorts, firmware/package context and every sample.

[PR #173](https://github.com/closure-labs/finite/pull/173) routed the new
qualification benchmark's custom GitHub reads through the declared SecretSpec
`repository-read` profile. The final qualification measurements above include
that wrapper and use execution source `f5b1408756393f8d649af067e1f10fb9faaca6e4`;
the qualified image source remains `2816fa4d16706a60e6cb91c616493aeeb7432101`.
Initial diagnostic runs are retained in the evidence but are superseded by these
wrapper-inclusive measurements. No new image, ISO or VM was generated for the
credential correction.

Inventory scans already used the same SecretSpec profile. Report aggregation and
the skipped DB-only receipt step now use it too. Independent review confirmed the
measured inventory-only reader paths are unchanged; no rescan was needed solely
for this report-collection wiring. Explicit summary tokens are confined to their
collection steps. Built-in artifact actions retain their normal scoped token.

All builds, native scans, DB work, ISOs and VMs stayed on GitHub-hosted runners.
Local work used source, small mocked fixtures, bounded text logs and authenticated
receipt/timing metadata. No local native inventory, image, ISO or DB was downloaded
or processed. Existing v0.8 releases and their original assets were preserved;
this work does not create or retag a public versioned release.

## Next decisions

1. Inventory reuse now has matched new-OS timing evidence for both active variants.
   Use an opt-in rollout with the same signature, exact-origin and fresh security
   checks before changing defaults.
2. Measure how often whole-qualification reuse finds an exact eligible hit. Keep
   its candidate/predecessor/context/source joins and original 24-hour deadline;
   compare observed hit rate with these per-hit costs before a global rollout.
3. These experiments do not demonstrate a benefit from Cachix writing or DB
   transport. Cachix writing remains false; inventory, DB and qualification reuse
   remain unset/default-off. Require their own complete-cost evidence before
   changing those defaults. No defaults or repository variables changed here.
