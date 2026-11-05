# Build the common image payload once per run

In [queue run 41895203864](https://github.com/closure-labs/finite/actions/runs/41895203864),
both profiles independently built the same 30 Nix derivations, including
`qxy0c9rz4m5f2ylivgf1ghba25av5drc-finite-image-payload-0.8.3-dev.drv`.
Authenticated artifact timings recorded 1,702.989 seconds for finite payload
staging and 1,679.697 seconds for finite-dev. The payload expression is shared;
the profile argument in `stage.sh` only validates the supported profile names.

The workflow now builds that existing locked payload in one read-only producer
job after source checks and image selection. It uploads one immutable Actions
artifact and passes its ID, archive SHA-256, checkout revision, run ID and producer
attempt through native job outputs. Both profile jobs consume those exact bytes.
BlueBuild assembly, profile recipes, upstream verification, image inspection,
security admission, signing, fresh/upgrade qualification and promotion gates
remain independent and required as before. Direct local `stage.sh` usage remains
available. Ordinary PR checks, empty image selections and immutable-candidate
resume requests do not start a payload compilation.

The new producer has a 45-minute timeout; existing consumer job limits are
unchanged. This adds a separate bounded prerequisite rather than promising the
same worst-case workflow duration. Actual combined cost requires hosted evidence.

This uses the pinned native [upload](https://github.com/actions/upload-artifact)
and [download](https://github.com/actions/download-artifact/blob/v8/README.md)
actions. A GNU tar file preserves modes and symlinks across Actions transport.
The archive is limited to 2 GiB, 2 GiB expanded content and 65,536 members, with
a 16 KiB context record. Source/run/attempt and digest checks precede extraction.
Duplicate names, traversal, special nodes, privileged modes and linked parents
fail closed. Absolute native-store links must point to members of the exported
runtime closure. Hard links are materialized as regular files; file bytes,
executable modes and symbolic-link targets match direct staging.

An explicitly carried successful producer may come from an earlier attempt of
the same run. Its actual attempt remains in the archive and verification record;
it is not relabelled as the consumer attempt. A future attempt, different run or
source, changed archive, missing native output or failed producer blocks the gate.
Resume still requires successful source checks and the normal publication path.

The producer has only `contents: read`; image consumers add `actions: read` for
the exact-ID download. There is no cross-run lookup, new cache writer, Cachix
publication, production credential or custom controller. The archive is retained
once for 14 days and excluded from the consumers' build-evidence uploads. Compact
verification records remain alongside their existing stage timings.

## Validation and measurement boundary

Offline fixtures compare native tar transport with direct `cp -a` plus the
existing writable-mode adjustment. They cover binary and registration bytes,
file modes, relative/absolute runtime links, corrupt/missing/stale artifacts,
source and attempt substitution, malformed context, traversal and size limits.
Selection/gate fixtures retain both VM profiles and fail on missing, cancelled,
failed or unexpectedly skipped producer work. Workflow lint and the normal
exact-head source/runtime aggregate remain required.

End-to-end savings are **not measured**. The old compilations ran in parallel,
so removing one duplicate build does not imply a 28-minute elapsed-time saving.
One producer setup and two artifact downloads add costs. Producer observations
record setup, build, archive size/member counts and archive time; native Actions
step timings provide upload/download duration, and each consumer records staging
time and the exact artifact context. Compare runner minutes, network/storage
bytes and total queue duration in a reviewed normal merge-queue run. No separate
benchmark cohort is introduced. Overlapping compilation with source checks, or
adding cross-run binary caching, would be separate decisions.
