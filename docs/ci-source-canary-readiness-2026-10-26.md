# Source-proof canary readiness, October 26 UTC

The [frozen native snapshot](ci-source-canary-readiness-2026-10-26.json.gz)
contains six natural main builds observed through `2026-10-26T16:04:03Z`.
All six workflows completed successfully. Its 42 unique native jobs account
for 2,772 runner seconds, including skipped jobs at zero. Grouped totals
conserve that occupancy. Collection downloaded bounded source receipts and
started no diagnostic hosted, Nix or VM execution.

The compressed snapshot SHA-256 is
`a64cb3c79ebd868d43e3357fd90f85ad5af91a801deeea136101b68ad68e2094`.
Earlier reports retain their original measurements and the original seven-day
endpoint remains `2026-10-30T05:01:17Z`.

Five consumers authenticated their exact successful protected-queue proof and
independently executed matching evaluation/build phases. Each source job and
its whole workflow passed. There are zero mismatches and zero enabled hits.
The earliest consumer has unknown eligibility from the previously corrected
credential wiring; it contributes its 410 runner seconds to cost, but cannot
count as either a match or a known miss.

| Successful shadow consumer | Whole source-job seconds | Nested proof lookup seconds |
| --- | ---: | ---: |
| [40268743648](https://github.com/closure-labs/finite/actions/runs/40268743648) | 367 | 2.874 |
| [40274425127](https://github.com/closure-labs/finite/actions/runs/40274425127) | 319 | 2.272 |
| [40326885272](https://github.com/closure-labs/finite/actions/runs/40326885272) | 396 | 4.177 |
| [40347208371](https://github.com/closure-labs/finite/actions/runs/40347208371) | 394 | 2.073 |
| [40354028046](https://github.com/closure-labs/finite/actions/runs/40354028046) | 368 | 2.323 |

These five source jobs total 1,844 seconds with a 368-second median. The lookup
intervals are already inside job occupancy. Each revision remains a separate
cohort; this baseline does not establish a causal speedup or enabled savings.

## Next bounded canary

The [five-comparison gate](ci-gate-consolidation-2026-10-25.md#exact-commit-source-proof)
is satisfied. Mode remains `shadow` in this snapshot. Enable the existing
switch for the next reviewed source-only main push when its rollout can be
observed, then return to shadow after the first completed consumer. Preserve
the native run, attempt, source job and producer artifact identities. Missing
or invalid evidence must execute full checks within that same workflow and
remain explicitly unknown or ineligible. Any correctness failure stops
consumption with `FINITE_SOURCE_PROOF_REUSE=off`.

Compare complete source-job occupancy with the exact referenced queue producer
and this shadow baseline, including setup, lookup, retention and cleanup.
Do not copy producer phase costs into the consumer or add nested durations.
PR, queue, scheduled and manual source checks continue executing the aggregate.
This canary changes no guest or installer behavior and grants no publication
authority. Approval, security freshness, signing and reservation checks remain
independent. The failed product-transport benchmark remains deferred; its
separate adoption gate is unchanged.

The report now counts shadow matches only after whole-workflow success and
exposes source-job costs grouped by exact revision, mode, eligibility, hit,
reason and job/workflow outcome. Failed and active work stays in accounting;
active elapsed occupancy is censored and excluded from completed medians.
Unknown duration is never replaced by zero, and duplicate native jobs across
retry projections are charged once.
