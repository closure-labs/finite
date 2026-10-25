# Shared channel payload evaluation, October 25 UTC

The channel reconciler computes each profile's expected image-input identity
before comparing public tags. Both profiles use the same generic Nix payload,
but the existing loop evaluates `lib/ci-payload.nix` independently for each
profile through `image_identity.identity`.

Evaluate that shared payload once per reconciliation invocation and pass its
derivation to the existing identity function. Each profile still hashes its own
recipe and the complete reviewed image inputs separately. Registry reads retain
their order, including the independent `finite`/`latest` alias comparison.
Every later invocation evaluates the payload again; this is not a retained
identity or authorization cache.

The command, root directory, inherited configuration, lock-file flags and
300-second timeout match the identity function's existing evaluation contract.
Tests compare the command directly with that unchanged implementation. The
identity implementation and hash schema are unchanged. The channel helper is
outside the OS input file set, and the generic payload's Nix expression does not
reference this helper, so this host-only change introduces no image-identity
migration or guest/installer behavior change.

## Natural baseline and verification limits

Two successful main jobs provide a baseline for the complete channel selection
step, before sharing the evaluation:

| Main run | Complete selection job seconds | Channel reconciliation step seconds |
| --- | ---: | ---: |
| [40175020315](https://github.com/closure-labs/finite/actions/runs/40175020315) | 59 | 25 |
| [40177783528](https://github.com/closure-labs/finite/actions/runs/40177783528) | 50 | 21 |

The [retained native baseline](ci-channel-payload-2026-10-25.json.gz) preserves
run/source/job identities and native step timings. The step includes environment
entry, Nix evaluation, file hashing and registry access. Individual payload
evaluation times are unknown. Reducing evaluator invocations from two to one
does not establish an end-to-end saving; follow natural complete-job results
rather than adding diagnostic VM or controller rounds.

The baseline archive SHA-256 is
`6869c49f13953d4d3c457464df48c3dba46401565eda382fd9a687c503aeaa42`.

The focused regressions establish one evaluator call per invocation, unchanged
real identities for both profiles, unchanged recipes and alias-read order, and
fresh evaluation when the next invocation has a different payload. Evaluator
errors/timeouts, invalid payloads and registry errors still fail the operation.
Invalid recipes fail before evaluating. Source selection retains the pinned
Nix/runtime aggregate and selects no image or VM work for this helper change.

## Current work list

PR 261's queue and main runs passed and selected no images. Its natural
controller also passed. The read-only report now identifies repeated recorded
source inputs while preserving unknown eligibility and hits. The
[source repetition report](ci-source-repetition-2026-10-25.md) retains the scoped
1,033 runner seconds and 883.664 nested phase seconds; required source checks
continue to run.

| Work | Classification | Next action |
| --- | --- | --- |
| Shared channel payload evaluation | Implemented; awaiting rollout measurement | One generic evaluator call replaces two; compare natural complete selection jobs after rollout. |
| Exact-source queue proof reuse | Requires design and validation | The measured repetition justifies investigation; no source-gate bypass is enabled. |
| Pending-security automatic full retries | Requires design | Authenticate candidate/source identity, freshness and retention before suppressing any recovery. |
| Shared decision-packet staging | Observed transport rollout; whole-job savings unestablished | Retain both per-profile integrity and independent authority checks. |
| Installer/runtime and product transport alternatives | Deferred adoption | Preserve stopped samples and correctness/performance gates, unseeded installs and actual bootc Home Manager activation. |

No approval, security-freshness, signing, reservation or publication rule changes.
Automatic Cachix writing and Grype database transport stay disabled. No local Nix,
image or VM run was performed. The original October 30 endpoint remains separate;
recent evidence supports this work now.
