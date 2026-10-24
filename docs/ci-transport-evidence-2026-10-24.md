# Transport evidence coverage, October 24, 2026 UTC

#243 merged at `9467e2e1a7e09fbf190a87a499dcae9c5040565f`. Its
[protected queue run](https://github.com/closure-labs/finite/actions/runs/40041690790)
passed the pinned aggregate and CI gate with image validation and publication
skipped. This is a source-only queue observation. The PR changes the classifier
itself; it is not a matched replay of #242's report-only change and does not
establish recurring frequency or a measured savings percentage. Preserve the
[earlier 1324-second observation](ci-cost-selection-2026-10-23.md).

The [companion record](ci-transport-evidence-2026-10-24.json.gz) retains native
queue metadata, authenticated partial transport samples, explicit gate reasons,
the collector hash and producer retention/cost evidence. Historical reports
retain their original snapshots.

## Existing transport matrix

The [diagnostic consumer run](https://github.com/closure-labs/finite/actions/runs/40037635079)
remains pinned to `6ef15e7e2d2d7eeca79cfc4edf0d62f9d416b6ed` and the same
immutable diagnostic packet. Six completed jobs have authenticated small
sample archives and passed correctness for the same 13,422,077,161-byte
two-profile inventory. No new producer, consumer matrix or VM was dispatched.

| Pair | Legacy complete seconds | Receipt complete seconds | Runner image comparison |
| --- | ---: | ---: | --- |
| Cold 1 | 426 | 237 | Both `20261012.334.1` |
| Warm 1 | 723 | 900 | Legacy `20261023.334.3`; receipt `20261012.334.1` |
| Warm 2 | 1716 | 1340 | Both `20261012.334.1` |

The tool cohort is identical in these six samples. Warm pair 1 remains an
unmatched result; do not drop or replace it. Warm pair 2 is faster through the
receipt path, but one matched warm pair cannot establish the five-pair median
gate. The partial record therefore reports six verified samples, zero failed
samples, consistent products, an incomplete sample set and a runner-image
mismatch. These are separate facts. It does not label missing samples as failed
product verification, zero-cost work or cache misses.

Producer occupancy remains a separate 1741 runner seconds. Complete consumer
job times include identical warm seed work, setup, transfer, hashing, artifact
retention and local cleanup. Provider cache state remains unknown. OCI retained
duration, billing/deduplication and exact-reference registry cleanup remain
unobserved. Production retains strict original ZIP verification. A better
partial median cannot override the original matching and lifecycle requirements.

## Native cost when samples are absent

The original reporter derives consumer costs from sample artifacts. A setup
failure can leave no artifact; an interrupted transfer can leave only timing
evidence. Such jobs must remain in the cost record even though they cannot
prove correctness. Enumerate native jobs independently, verify their run,
attempt and source, deduplicate identical job IDs and retain conflicting
records as errors. Include setup, retention and post-job handling through native
start/completion timestamps, as exposed by the
[GitHub workflow jobs API](https://docs.github.com/en/rest/actions/workflow-jobs).

The report adds native job accounting, a known-duration subtotal, unknown
duration IDs, missing native/sample jobs and unscored sample evidence. Unknown
or zero-resolution durations cannot become fast successful samples. A failed
workflow cannot pass the gate even if its available product samples passed.
When no sample identifies a producer, its cost remains explicitly unknown.
Otherwise verify the native producer run and successful producer job, then
record its complete cost separately without double charging duplicate IDs.

Present malformed samples, invalid archive digests, mismatched origins,
duplicate pairs and conflicting native jobs remain terminal errors. An absent
sample member is partial evidence only when its bound native job failed. The
reader accepts one unretried comparison, at most twelve 1 MiB sample archives,
at most 100 native jobs/artifacts per inventory and one 60-second GET per small
archive. Product transport keeps its existing retry and verification behavior.

Each pair exposes runner image and tool cohort values, missing modes, and
matched/unknown/mismatched states. Stable gate reasons distinguish incomplete
evidence, sample failure, cohort mismatch, unknown cohorts, the two warm
thresholds, cold regression, failed native runs and unknown native costs. These
are additive report fields; dispatch inputs and product/qualification formats
are unchanged. The two reviewed reporting helpers retain source checks without
selecting image work; unknown helpers and mixed boot changes remain conservative.

The reporting follow-up remains draft under the original benchmark plan. It
does not enable production or make publication decisions. The running matrix
and bounded read-only collector continue. The seven-day endpoint remains
`2026-10-30T05:01:17Z`; later cohorts remain separate. Installer-runtime reuse
and guest closure transport remain proposals pending avoidable-cost evidence.
Cachix writing and Grype database transport remain disabled.
