# Bounded security-image transfer experiment

The October 28 natural build at `29ff94251593c51eb08c4fef11a1fad15f69ea25`,
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

## First hosted attempt: inconclusive, before transfer

[Run 40761439573](https://github.com/closure-labs/finite/actions/runs/40761439573)
failed all six arms before launching the copy worker. Signatures passed, but the
bound BuildKit attestation used the canonical empty OCI configuration:
`application/vnd.oci.empty.v1+json`, two bytes `{}`, digest
`sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a`,
embedded as `e30=`. Applying native-image configuration rules to that attestation
incorrectly rejected it. The exact 839-byte attestation manifest is retained as
an offline regression fixture, not as authority to skip signature verification.
Its test removes exactly one repository-required terminal newline before checking
the original 839-byte SHA-256.

The correction admits only that exact canonical configuration on an attestation
with the expected artifact type and an exact native subject descriptor. Native
and shared descriptor validators remain unchanged. Inline bytes must match
canonical data, size and digest, and the two-byte blob must still appear in the
copied layout and pass independent hashing; it is neither omitted nor synthesized.

The attempt also revealed five strict hardware cohorts across six independent
jobs. The fix below uses one host rather than relaxing CPU/RAM/kernel equality.
The failed summary previously accessed absent success-only `binding` fields;
failed receipts now produce a readable `inconclusive` summary with outcomes,
no medians, and a nonzero exit. This attempt establishes **no memory, throughput
or savings result** because the bounded copy workers never ran.

The separate [first DB experiment](https://github.com/closure-labs/finite/actions/runs/40765793821)
subsequently exposed a shared diagnostic assumption: a successful scan's cgroup
peak was 8,192 bytes above its enforced limit with zero OOM/kill counters and
12,988 max-boundary events. This was not a transfer measurement, but offline
fixtures reproduced the same false rejection in this harness. The
[kernel documents temporary `memory.max` overshoot](https://docs.kernel.org/admin-guide/cgroup-v2.html#memory-interface-files).
The correction below separates enforced limits from observed peak telemetry;
it does not raise the transfer cap or infer a performance gain from that scan.

## Controlled execution

- Select one existing **signed linux/amd64 image or parent index** by digest,
  its exact source revision, profile and `io.finite.build-inputs` identity.
  Parent indexes admit one native image and only bound attestation children,
  at most eight manifests total. Every copied child/config/layer contributes
  to the preflight byte budget and post-copy independent digest verification.
  Unknown alternate-platform children fail before transfer. The signature stays
  bound to the original parent; never substitute an unsigned child digest.
- One fresh `ubuntu-24.04` job runs six sequential arms on the **same host**:
  three adjacent pairs in fixed order **1→2, 2→1, 1→2**. Three pairs cannot fully
  balance order, so ordering effects remain a limitation, not a hidden control.
  Every arm starts with a new empty private OCI layout and home. There is no
  Actions/Nix-store restore or image cache seeding. Tool setup is shared once.
  CPU model/count, total RAM, kernel and runner-image cohort must match; initial
  available memory is retained separately. A failed arm stops later transfers,
  which are explicitly marked not-run; no slow/failing sample is silently dropped.
  Fresh layouts do **not** establish cold OS, filesystem, DNS or registry/CDN
  caches. No global cache flush is performed. Cache/order effects, unrelated
  runner traffic and time-varying network load remain uncontrolled.
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
- The owned cgroup's exact memory, swap and task caps must match before and
  after the copy. Peak telemetry is not clamped or compared to an invented
  page/percentage tolerance. A positive integer peak must fit **pre-arm available
  memory minus the existing 4 GiB reserve**, bounded by physical RAM. Parent and
  worker observations must agree, and physical RAM must match the runner cohort.
  This is a conservative observation budget, not a larger kernel limit or proof
  of continuous host headroom. Missing/malformed counters, any OOM/group-kill,
  timeout, nonzero exit or unconfirmed cleanup remain failures. Post-copy
  telemetry errors are retained even when the native command also failed.
- Only small measurements/metadata/logs are uploaded, never image blobs or
  credentials. No image is executed, built, signed or published. Workflow
  permissions are read-only, and it does not request signing/write secrets.

Run manually after review, choosing the branch containing the workflow and
explicit immutable inputs. Do not dispatch on a floating tag. A full invocation
has one paired job capped at 270 minutes plus one 10-minute summary job: a hard
workflow ceiling of **280 runner-minutes**, not expected runtime or billed cost.
The single concurrency group prevents overlapping diagnostic runs. There is no
schedule or automatic PR trigger, and this PR does not dispatch the benchmark.

## What the receipts mean

Each arm retains signature/metadata, transfer and independent-integrity
durations, blob bytes, blob-bytes/transfer-second throughput, cgroup peak memory,
failure/timeout/exit outcome and runner network deltas. Blob throughput is **not
wire throughput**: retry traffic/protocol overhead differ, and runner network
bytes include other activity. Transfer time includes the configured retry policy.
Private layout cleanup remains included in the arm diagnostic total. The shared
tool/setup cost is recorded **once** in `paired.json`, not attributed to each arm.
Per-arm setup markers exclude that shared preparation and all preceding arms.
Each memory observation retains the exact peak, enforced limit, overage,
pre-arm budget and max/high boundary counts. The aggregate explicitly flags
limit pressure; constrained peak memory is not unconstrained memory demand.

The summary requires all six successful, uniquely identified arms and identical
image/source/provenance, lock/tool versions, signing key, runner image/hardware,
cache/resource policy and verified bytes. It rejects incomplete, failed,
timed-out or mismatched cohorts instead of dropping slow/failing samples.
Raw failed-arm receipts and explicit not-run outcomes remain in the artifacts.
The summary verifies the fixed sequence and non-overlapping timestamps inside
the paired session. It reports per-arm medians and each pair's copy-time delta
and ratio. Complete same-attempt GitHub job timestamps bind run, attempt and
revision and give **one whole-experiment-job total**, including shared setup,
all six arms, artifact upload and post-job work. Queue wait is excluded. There
is no per-arm whole-job comparison: the JSON explicitly records
`perArmWholeJobComparisonAvailable: false`. Incomplete or failed sessions never
produce performance medians or pair ratios.

No extraction, uncompressed DiffID validation, inventory, DB refresh or complete
security scan is performed in this transport-only experiment. Production still
performs those checks. Whole **benchmark-job** times must not be represented as
whole **security-job** timings. A later production proposal needs complete scan
validation with the same security checks and resource limits, repeatable matched
cohorts, no integrity/failure regression, acceptable memory headroom and human
review. The summary always records `productionChangeRecommended: false`.

## Validation status

Executed locally: small offline integrity, resource/credential guards, bounded
log handling, command-flag equivalence, canonical-attestation anti-forgery,
same-host ordering, failure classification and whole-experiment timing tests,
plus permitted peak overshoot, unchanged exact caps, pre-arm/cohort binding,
complete OOM counters and post-copy failure-evidence retention.
No local multi-GiB download or image execution was performed. The first hosted
attempt failed before transfer; the corrected real cgroup/systemd and throughput
measurements remain **deferred pending review and a deliberate rerun**. No
performance improvement is claimed.

```sh
python3 tests/ci/image-transfer-benchmark.py
python3 tests/ci/image-verification-benchmark.py
python3 tests/ci/selection.py
python3 tests/ci/workflow-lint.py
```
