# Home Manager evaluation result, October 24, 2026 UTC

Retain serial evaluation. The completed hosted trial produced identical public
aggregate derivations, check inventories and all twelve Home Manager proof
paths in both strategies, but paired evaluation failed its performance gate.
The [retained record](ci-home-proof-evaluation-2026-10-24.json.gz) includes the
complete comparison, per-sample memory/timing data and failed setup attempts.

## Matched comparison

The [completed diagnostic](https://github.com/closure-labs/finite/actions/runs/40057850953)
uses immutable source `8add9670c755a7ab02ae685360af45fc8f949853`, retained on
the [audit branch](https://github.com/closure-labs/finite/tree/audit/ci-home-proof-pairs-20261024).
Its Foundation input is **v0.3.2**, revision
`235c34d7e507f00c2df6b0102bcdb54a4c04c5e2`. Later Foundation inputs are a
separate cohort; this experiment makes no performance claim for v0.3.3.

One runner and checkout evaluated the public aggregate as an unscored seed,
then ran three serial/paired comparisons in order
`serial, paired, paired, serial, serial, paired`. Flake evaluation caching was
disabled in both arms. Source and derivation caches were warm after the seed.
Every comparison fingerprint matched the public aggregate, including all check
names, profile identities and activation derivation paths.

| Warm complete evaluation | Serial | Paired |
| --- | ---: | ---: |
| Median seconds | 95.853 | 105.742 |

The median difference is **-9.889 seconds saved**, failing the required
10 percent and 10 second improvement. A single paired sample took 59.827
seconds; it does not replace the full median. Both strategies stayed within
the 6 GiB service limit with swap disabled. The largest measured evaluator
RSS was 5961092 KiB. RSS describes the evaluator, not total service memory.

The completed native job costs **799 runner seconds**, including setup, the
182.121-second public seed, evaluation, retention upload and cleanup. Warm
medians do not amortize those costs away. Earlier setup failures at separate
heads cost **239** and **202** runner seconds. Their partial results remain
in the record and are excluded from successful performance samples. Total
known diagnostic occupancy is **1240 runner seconds**; normal PR verification
is separate and is not included in that subtotal.

The first setup failure did not explicitly apply the diagnostic Nix function.
The second needed an explicit shallow Git reference. The preserved diagnostic
adds a real CLI fixture and a cheap revision/check-count preflight before the
public seed. Neither failure establishes an evaluator performance result.

The unsuccessful production scheduling change and its experimental workflow
are excluded from the current PR. Keep the existing strict, serial proof
matrix, evaluator/build sequencing and full pinned `.#ci-checks` aggregate.
Future scheduling experiments require fresh evidence for their exact input
and tool cohort. No installer or guest behavior is changed by this result.

## Natural source observations

The authenticated [#246](https://github.com/closure-labs/finite/pull/246)
receipts identify evaluation as the largest part of the source aggregate.
These samples are separate rollout observations, not a matched comparison.
Phase intervals are nested within native job occupancy and are not added to it.

| Run | Source job seconds | Evaluation seconds | Build seconds | Setup seconds |
| --- | ---: | ---: | ---: | ---: |
| [PR](https://github.com/closure-labs/finite/actions/runs/40047984885) | 410 | 290.909 | 72.051 | 30.846 |
| [Queue](https://github.com/closure-labs/finite/actions/runs/40049087565) | 312 | 208.517 | 59.018 | 30.154 |
| [Main](https://github.com/closure-labs/finite/actions/runs/40052937117) | 360 | 259.445 | 53.542 | 29.127 |

The main rollout completed both profiles' fresh-install and upgrade/rollback
qualification and both promotions successfully. Earlier obsolete-source checks
executed successfully before image and security work. This current-source run
does not measure avoided obsolete work or establish savings from the guards.

Restored cache keys are observed, while historical hit values remain unknown.
The pinned [cache action outputs](https://github.com/nix-community/cache-nix-action/blob/7df957e333c1e5da7721f60227dbba6d06080569/action.yml)
declare `hit`, not `cache-hit`. Correct that observation wiring for future
receipts without changing restoration, save policy or historical values.

## Foundation v0.3.3 and follow-up

The current candidate adopts the published [Foundation v0.3.3 release](https://github.com/closure-labs/foundation/releases/tag/v0.3.3)
at immutable revision `0391c2e7bf7284ba0e999be73046cf03a0601918`, with NAR hash
`sha256-7G9HKe8AH4pVi1gWY0//KENgC9e97ezlEof3hsuZV1g=`. Only the Foundation
node changes in Finite's lock; Foundation's own dependency lock is unchanged.
The release installs the Home Manager CLI in new homes and validates release
metadata before publication. It requires the normal source/image/bootstrap
checks and both profiles' fresh-install and upgrade/rollback qualification.

Bound Foundation release resolution to 15 minutes while preserving the
270-minute orchestration allowance checked by delivery policy. Resolution
performs metadata lookup and lock generation; no Home Manager aggregate or
VM build runs in this step. This limits stalled work; it is not a measured
steady-state speed improvement.

Installer runtime/compression and guest closure transport remain proposals.
The [transport result](ci-next-optimization-2026-10-24.md) retains legacy
original-ZIP production verification. Cachix writing and Grype database
transport remain disabled. The original seven-day endpoint remains
`2026-10-30T05:01:17Z`, with later cohorts separate and incomplete.
