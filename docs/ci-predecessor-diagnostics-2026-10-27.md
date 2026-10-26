# Bounded predecessor ISO reuse diagnostics, October 27 UTC

The [recent cost sample](ci-recent-rollout-2026-10-26.md) found two eligible
predecessor-ISO misses, but their native logs retained only a generic exhausted
lookup message. Diagnose those misses before changing generation-input coverage
or repeating expensive installer experiments.

## Observation contract

The existing production upgrade lookup now writes one versioned
`finite-predecessor-iso-reuse` JSON observation beside its other phase evidence.
It records the native repository, source, run/attempt, profile and requested
predecessor digest; final outcome; examined run/artifact counts; and fixed miss
reason counters. It explicitly grants no publication authority.

Reasons distinguish no successful runs, no live qualification artifact,
unavailable qualification metadata, legacy evidence, candidate/profile mismatch,
missing or changed generation inputs, other generation ineligibility, missing
preserved ISO, missing installation tag and the existing recognized ISO transfer
timeout. Metadata unavailability is not inferred to mean a particular age or
integrity problem. A successful later candidate can retain earlier rejection
counters. Counts describe searched artifacts, not independent workflows or a
fleet-wide cache miss rate.

At most 20 changed input paths of at most 200 ASCII characters are retained.
Only labels owned by the current source may enter that sample. Unknown recorded
paths still reject reuse and mark the sample truncated; their raw labels are not
logged. Samples exclude absolute paths, traversal and control characters. Counter
keys are fixed and reason counts saturate at one million. The cost reader caps
the entire observation at 16 KiB, in addition to its existing authenticated ZIP
and entry bounds. No extra API request or upload-artifact job is introduced.

The file is published atomically with exclusive creation. An interrupted write
cannot leave a partial final JSON file; a later invocation cannot replace earlier
observations. Missing files remain unknown. Observation-write failures preserve
the original command status, so diagnostics cannot authorize reuse or turn a
signature/integrity rejection into a rebuild fallback.

The native phase artifact retains the file even after a failed phase. The
read-only cost collector authenticates the enclosing artifact and binds the
observation to the exact native production upgrade job, profile, source,
run/attempt and artifact name. It rejects wrong origins, wrong phase/profile,
unknown reason codes, oversized samples and conflicting duplicates. When the
measured command status is present, it must agree with the diagnostic outcome.
JSON reports retain the detailed counters in `predecessorReuseDiagnostics`;
legacy or missing observations retain an explicit null value.

## Reuse behavior

The acceptance, source-input projection, signature/hash/origin checks, artifact
search, ten-minute ISO transfer budget and same-signed-predecessor rebuild
fallback remain as before. Ordinary misses return status 3, accepted restoration
returns 0, and rejected/integrity failures return 2. Fresh installs and manual
branch diagnostics do not execute this optional production predecessor lookup.
No guest configuration, Home Manager initialization or VM acceptance changes.

The phase workflow and qualification wrapper remain generation inputs. This
instrumentation can itself cause a conservative first-rollout context miss.
Do not relax that identity or treat that expected possibility as observed proof.
Collect the first natural production upgrade receipt before attributing prior
misses to a specific input change.

## Verification

181 focused qualification, native collection, cost accounting, graph-contract,
selection and toolchain tests passed. Regressions cover bounded and omitted
paths, atomic interrupted writes, existing-file/symlink destinations, missing
artifacts/tags, legacy/changed contexts, the recognized transfer timeout, wrong
origins, forged archives, failed signatures, conflicting receipts and error
versus miss versus unknown. Documentation checks, the checked Actionlint adapter
and offline Zizmor passed. The pinned hosted aggregate is required before merge;
no local Nix evaluation/build or VM round was run.
