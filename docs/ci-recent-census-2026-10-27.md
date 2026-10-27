# Recent CI cost census and diagnostics rollout, October 27 UTC

PR #286 merged as `3c03a6f9c11fd121452238e1a5163e0774c0c0cf` after both
[queue VM profiles](https://github.com/closure-labs/finite/actions/runs/40425473368)
passed. Its [main run](https://github.com/closure-labs/finite/actions/runs/40430851552),
[delivery health](https://github.com/closure-labs/finite/actions/runs/40431076325)
and [decision reconciliation](https://github.com/closure-labs/finite/actions/runs/40431076301)
also passed. Main selected no images. Its only artifact was the source-check
receipt: no production upgrade ran, so no natural predecessor-reuse diagnostic
was expected or retained. The first natural miss cause remains unknown.

The full pinned hosted aggregate passed for the diagnostics implementation;
181 focused regressions passed beforehand. Keep the
[diagnostics contract](ci-predecessor-diagnostics-2026-10-27.md) and all existing
origin, signature, hash, generation-context and acceptance checks. The relocated
production preflight from #285 also still awaits a natural publication run.
Do not dispatch another full VM round only to manufacture this evidence.

## Complete recent native cohort

The census covers every workflow run created from October 26 19:30:00 UTC through
October 27 01:30:00 UTC, with the end excluded. It counts each selected run's full
native job lifetime, rather than clipping execution at the time-window boundary.
The complete inventory was checked again after collection and remained stable.

The [compressed census](ci-recent-census-2026-10-27.json.gz) retains 159 runs and
377 native job observations. Of those jobs, 207 used runner time; skipped jobs
retain zero occupancy. Native and grouped occupancy both equal 36,246 seconds,
with zero unknown job durations. The runs concluded with 96 successes, 61 skips
and two failures. Real retries and failed work remain charged; copied native
check-run aliases retain the existing unique-execution accounting.

This completes a recent bounded census, not the original seven-day observation
ending October 30 05:01:17 UTC. It supersedes the earlier five-run selection for
recent frequency accounting while preserving that frozen sample and its costs.
The interval contains several source/tool rollouts; none of their differences
are attributed wholesale to the original VM-tool change.

| Workflow work / event | Runner jobs | Runner seconds |
| --- | ---: | ---: |
| Queue build/export/ISO/VM validation / merge group | 6 | 15,326 |
| Production upgrade and rollback / push | 2 | 4,334 |
| Production fresh install / push | 2 | 3,343 |
| Source contracts / pull request | 5 | 2,011 |
| Source contracts / merge group | 4 | 1,499 |
| Fresh image security / push | 2 | 1,499 |
| Maintainer authority / workflow completion | 21 | 1,329 |
| Decision reconciliation / workflow completion | 4 | 894 |
| Image build / push | 2 | 689 |
| CodeQL, native role unknown / pull request | 12 | 686 |
| CodeQL, native role unknown / push | 8 | 584 |
| CodeQL, native role unknown / merge group | 8 | 534 |
| Decision reconciliation / schedule | 2 | 394 |
| Source proof consumers / push | 4 | 283 |

Rows summarize native frequency across the interval. Complete JSON cohorts keep
workflow, event, profile, exact revision and outcomes separate. These are runner
occupancy figures, not billed amounts or causal speedup estimates. Exact
cross-workflow dependency contributions remain unknown. Sole-runner intervals
are within-workflow lower bounds; observed final-job counts identify only the
workflow tail. Neither substitutes for an authenticated full dependency graph.

The six queue validation jobs and four production qualification phases account
for 23,003 seconds. That ranks installer/VM work first by occupancy, but does not
prove which part is avoidable. Preserve unseeded fresh coverage and actual bootc
Home Manager activation. The upstream runtime's candidate-specific upgrade
configuration and incomplete signed RPM/runtime identity still block safe
installer-runtime reuse. Guest closure transport still needs Foundation's
internal evaluation/fetch/realization and activation timings.

## Evidence limits and failures

The fixed receipt budget read 28 authenticated archives. Six older runs have no
new receipt join because fewer than sixteen budget slots remained; their complete
native job costs still count. The two large full security archives exceeded the
reader bound; their compact timing archives were read. The separate targeted
[recent rollout report](ci-recent-rollout-2026-10-26.md) retains earlier stage
measurements, without pretending those archives were reread in this census.
Missing receipts or detailed reuse identity remain unknown, not zero or a miss.

The failed #285 source attempt used 453 runner seconds. The other failure,
[scheduled health 40393114565](https://github.com/closure-labs/finite/actions/runs/40393114565),
used 84 seconds. Its authenticated health snapshot reported the old failed
main aggregation in `40367978697`, before #283 repaired carried-attempt collection.
Decision-pipeline health itself passed, while delivery health correctly retained
that latest-main failure. Current #286 callbacks passed. Do not suppress the old
failure or diagnose unrelated runner-monitor warnings as its cause.

Four main source jobs authenticated exact queue proofs, taking 91, 68, 71 and
53 runner seconds at their separate revisions. Lookups took 2.321, 2.874, 2.773
and 2.272 seconds respectively; none executed consumer aggregate evaluation/build.
Ordinary PR and queue validation remained enabled. The first failed PR's cost is
still present, so the census does not select only successful proof consumers.

The exact-head #286 review at 00:12:55 UTC also produced an automatic successful
[authority recheck](https://github.com/closure-labs/finite/actions/runs/40424969963)
at 00:14:23, an observed 88-second recovery with no manual restart. CI execution
was already running: this demonstrates recovery of an earlier rejected authority
status, not a GitHub external-contributor execution-hold repair or a latency
guarantee. Retain the existing event, periodic and manual recovery paths.

## Remove a measured duplicate scanner event

The effective branch rules require `CI gate` and `Maintainer decision authority`,
not CodeQL or a required code-scanning rule. Their snapshot is included in the
compressed evidence. Authority is triggered by its independent merge-group event
collector, so it does not depend on CodeQL completion.

Remove CodeQL's merge-group trigger while preserving both languages, categories,
pinned actions, PR analysis, main-push analysis, weekly scheduling and manual
runs. Keep the Build Finite and authority collector merge-group triggers. The
[GitHub requirement](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks)
for a queue event applies to required checks; if CodeQL becomes required later,
restore its queue event as part of that policy change.

The four queue scanner workflows used eight runner jobs and 534 seconds in this
window. This is the measured removal opportunity at the observed frequency,
not a fleet projection or a demonstrated reduction in workflow latency. Main
continues to scan each merged revision. Treat edits to the static-analysis
workflow as source checks without selecting OS images; unknown CI paths and
actual payload changes retain conservative selection. Source/security regressions
and the pinned aggregate remain required before merging this change.

## Next measured decision

The current same-source serial controller used 164 runner seconds. It retained
the existing already-dispatched outcomes for both profiles, with no new build
dispatch. Its event was a completion callback, so it is context rather than a
matched baseline for a scheduled canary.

A single natural four-worker historical-read canary is preregistered against
that exact source, ledger, packet and declared tools. Its supervisor restores the
absent serial-default option when the controller step begins, or at the bounded
trial deadline. It neither dispatches a workflow nor changes live-approval checks.
The following natural same-source scheduled serial run is the matched control.
Adoption requires correct results, the same observed runner/Nix cohort and at
least 10 percent and ten seconds lower complete-job occupancy. One pair does not
authorize automatic ongoing adoption or establish fleet-wide savings.

Retain the sample if it fails, lacks a matching control or encounters a source/
cohort change. Keep ongoing production serial until a reviewed adoption decision.
The temporary trial and its cleanup/comparison state are recorded separately
from this closed cost window; their native costs belong to a later cohort.
