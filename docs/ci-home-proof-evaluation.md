# Home Manager proof evaluation trial

The authenticated observations from [#246](https://github.com/closure-labs/finite/pull/246)
identify evaluation as the largest part of the source aggregate in two natural
runs. These are separate rollout samples, not a matched performance comparison.

| Run | Complete source job seconds | Evaluation seconds | Build seconds | Setup seconds | Runner image |
| --- | ---: | ---: | ---: | ---: | --- |
| [PR](https://github.com/closure-labs/finite/actions/runs/40047984885) | 410 | 290.909 | 72.051 | 30.846 | 20261012.334.1 |
| [Queue](https://github.com/closure-labs/finite/actions/runs/40049087565) | 312 | 208.517 | 59.018 | 30.154 | 20261023.334.3 |

Phase timings are nested within native job time. Restored store keys are
observed; the missing cache-hit outputs remain unknown. No savings are inferred
from the different runner images or complete-job durations.

## Candidate change

The scalar aggregate evaluation currently forces its Home Manager proof matrix
sequentially. Extract the existing matrix without changing profile identities,
case order, constructor or derivation paths. It still checks every foundation
and hardware combination, each role, all roles together and all packages.

The candidate schedules at most two independent derivation paths at once.
Each background task deeply forces its path. The foreground deeply forces the
same pair, retaining errors, before the next pair starts. Upstream Nix clients
without the primitive use the serial path. Existing measured evaluation-thread
and memory budgets remain in place. The public aggregate still evaluates once,
releases its evaluator and builds exactly its resulting derivation.

Determinate documents [explicit parallel evaluation](https://docs.determinate.systems/determinate-nix/parallel-eval/).
Its [primitive implementation](https://github.com/DeterminateSystems/nix-src/blob/main/src/libexpr/parallel-eval.cc)
starts background evaluation and returns its second argument. Returning a
constant alone would not preserve strict checks; the foreground assertion is
required. Pure fixtures verify the matrix, serial fallback and failures nested
inside a role's derivation path. Hosted verification exercises the installed
pinned client and the full real matrix.

## Bounded hosted comparison

The existing manual cache benchmark has an optional `evaluation_only` lane.
It runs one evaluation job and skips the original cache matrix and summary.
No image build, VM round, publication credential or cache upload is needed.
Its default behavior remains the existing cache experiment.

First evaluate the public pinned aggregate as an unscored seed. Then compare
serial and paired scheduling three times each on the same runner and checkout,
with order `serial, paired, paired, serial, serial, paired`. The diagnostic
entry uses the same module tree and changes only the internal proof scheduler.
Every result includes the complete aggregate derivation, all check names and
every profile/activation derivation path. All seven fingerprints must match.
This also proves that the diagnostic target matches the public aggregate.
Force the aggregate before serializing its diagnostic fields so automatic
parallel JSON serialization cannot change the serial baseline's scheduling.
Use an explicit Git flake reference, keeping untracked benchmark receipts out
of the evaluated source just as the public flake does.
The reference explicitly permits the workflow's shallow checkout. A cheap
preflight validates the Git revision, check names and proof count before the
seed, without forcing activation derivations.

Each evaluator runs in its own service cgroup with `MemoryMax=6G`,
`MemorySwapMax=0` and a 900-second runtime limit. Services run as the runner
user and stop before the next sample. Retain status, wall time including
launcher/cleanup, maximum evaluator RSS and failed/partial results. The entire
service is memory limited; maximum RSS describes the evaluator process, not
the service's total peak memory. Unknown metrics cannot qualify a trial.

Flake evaluation caching is disabled in both arms. Source and derivation caches
are warm after the seed. Seed, setup, retention and cleanup costs remain part
of native complete-job occupancy; warm medians do not amortize them away. The
small proof matrices, sample receipts and report are retained for 14 days.

Keep the candidate draft until the exact matrices and full pinned aggregate
pass, warm evaluation medians improve by at least 10 percent and 10 seconds,
and every measured evaluator stays within the memory bound. This is a source
evaluation trial on one runner, not a guarantee about future job savings.
Use subsequent natural complete jobs to validate the recurring benefit.

Image and guest behavior, fresh-install coverage, actual Home Manager
activation and the independent publication/security/approval checks remain
required. Installer reuse and guest closure transport remain proposals. The
[transport result](ci-next-optimization-2026-10-24.md) retains the legacy
production path. The original seven-day endpoint is still
`2026-10-30T05:01:17Z`; later rollout cohorts remain separate.
