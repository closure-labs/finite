# Bounded security-image transfer experiment

The latest natural build at `29ff94251593c51eb08c4fef11a1fad15f69ea25`,
[run 40704887511](https://github.com/closure-labs/finite/actions/runs/40704887511),
reported `finite-dev` image transfer **508.218 s**, rootfs extraction **123.803 s**,
cataloging **251.953 s**, fresh DB acquisition **56.181 s** and vulnerability
scanning **23.074 s**. Its whole security job was **1,098 s**. The corresponding
`finite` transfer was **97.281 s**. These are unmatched observations, not evidence
that more parallel copies improve throughput or total security time.

## Question and unchanged safety boundary

Does changing only skopeo's `--image-parallel-copies` from **1 to 2** improve a
bounded immutable transfer without increasing failures or unacceptable memory?
Production `security-scan.py` remains at **1**. It previously moved away from
memory-heavy registry materialization; this experiment does not remove the cap.
Admission, signatures, manifest/config/layer verification, rootless extraction,
fresh Grype DB update, coverage checks and policy evaluation remain unchanged.

The new manual **Benchmark bounded image transfer** workflow reuses the existing
image-verification helper's metadata/provenance validation rather than building
another Docker daemon benchmark. It uses the same skopeo copy flags as the
scanner (`--all --preserve-digests --src-no-creds --retry-times 3`). Only copies
1 and 2 are admitted. The existing Docker registry-verification diagnostic and
its unresolved same-build dual-export question remain separate.

## Controlled execution

- Select one existing **signed linux/amd64 image or parent index** by digest,
  its exact source revision, profile and `io.finite.build-inputs` identity.
  Parent indexes admit one native image and only bound attestation children,
  at most eight manifests total. Every copied child/config/layer contributes
  to the preflight byte budget and post-copy independent digest verification.
  Unknown alternate-platform children fail before transfer. The signature stays
  bound to the original parent; never substitute an unsigned child digest.
- Six independent fresh hosted jobs: three samples per arm, `ubuntu-24.04`,
  maximum one active transfer job. Each starts with a new empty private OCI
  layout and home, no Actions/Nix-store restore and no image cache seeding.
  CPU model/count, total RAM, kernel and runner-image cohort must match; initial
  available memory is retained separately. Matrix order is not an execution-order
  guarantee. Remote registry/CDN caches,
  network locality and unrelated runner network activity remain uncontrolled.
- Both arms use a **fixed 4 GiB cgroup memory cap**, no swap, 4 GiB available
  memory reserve, 64 tasks and a 30-minute service lifetime. This is intentionally
  narrower than the production scanner's adaptive maximum of 10 GiB, not a
  reproduction of its complete memory envelope. Insufficient headroom fails
  before transfer; cap errors never automatically retry with larger resources.
- The preflight authenticates the signature and exact manifest/config bytes,
  validates image labels/platform and bounds the whole copied blob graph to 32 GiB.
  Available disk must cover all declared layer bytes plus 4 GiB. After transfer,
  the copy's digest file and OCI index must match the original manifest; every
  unique manifest/config/compressed-layer blob is independently stream-hashed
  against its digest and size. Extra, missing, linked or corrupted blobs fail.
- The worker snapshots `memory.peak` **inside its cgroup before exit**, avoiding
  a race with successful unit unloading. This includes the helper, skopeo and
  accounted page cache, not just Go heap or one process's RSS. The copy remains
  inside the same cap while writing all image layers; no small log-file rlimit
  is inherited by layer writes. Retained command logs are capped at 1 MiB.
- Only small measurements/metadata/logs are uploaded, never image blobs or
  credentials. No image is executed, built, signed or published. Workflow
  permissions are read-only, and it does not request signing/write secrets.

Run manually after review, choosing the branch containing the workflow and
explicit immutable inputs. Do not dispatch on a floating tag. A full invocation
has six jobs capped at 45 minutes each plus one 10-minute summary job: a hard
workflow ceiling of **280 runner-minutes**, not expected runtime or billed cost.
The single concurrency group prevents overlapping diagnostic runs. There is no
schedule or automatic PR trigger, and this PR does not dispatch the benchmark.

## What the receipts mean

Each arm retains setup, signature/metadata, transfer and independent-integrity
durations, blob bytes, blob-bytes/transfer-second throughput, cgroup peak memory,
failure/timeout/exit outcome and runner network deltas. Blob throughput is **not
wire throughput**: retry traffic/protocol overhead differ, and runner network
bytes include other activity. Transfer time includes the configured retry policy.
Private layout cleanup remains included in the diagnostic total.

The summary requires all six successful, uniquely identified arms and identical
image/source/provenance, lock/tool versions, signing key, runner image/hardware,
cache/resource policy and verified bytes. It rejects incomplete, failed,
timed-out or mismatched cohorts instead of dropping slow/failing samples.
Raw failed-arm receipts remain in their artifacts even when aggregation fails.
Complete same-attempt GitHub job timestamps bind run, attempt and revision and
include setup, artifact upload and post-job work. Queue wait is excluded.

No extraction, uncompressed DiffID validation, inventory, DB refresh or complete
security scan is performed in this transport-only experiment. Production still
performs those checks. Whole **benchmark-job** times must not be represented as
whole **security-job** timings. A later production proposal needs complete scan
validation with the same security checks and resource limits, repeatable matched
cohorts, no integrity/failure regression, acceptable memory headroom and human
review. The summary always records `productionChangeRecommended: false`.

## Validation status

Executed locally: small offline integrity, resource/credential guards, bounded
log handling, command-flag equivalence, drift/failure/whole-job aggregation and
workflow/selection contract tests. No local multi-GiB download or image execution
was performed. Full hosted cgroup/systemd and throughput measurements are
**deferred**; this draft provides the controlled experiment, not savings results.

```sh
python3 tests/ci/image-transfer-benchmark.py
python3 tests/ci/image-verification-benchmark.py
python3 tests/ci/selection.py
python3 tests/ci/workflow-lint.py
```
