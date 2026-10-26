# CI gate consolidation, October 25 UTC

PR 264's protected queue, main build and natural controller passed. The queue
used 446 runner seconds, main 467 and the controller 168. The preceding natural
controller used 141 seconds in a different, unmatched observation. Shared
immutable-document correctness and the component comparison do not establish
complete-job savings. The earlier
[immutable document report](ci-immutable-documents-2026-10-25.md) retains its
original measurements.

## Remove duplicate proposal approval reads

The App check previously authenticated approval before inspecting proposal
documents, then each proposal verifier authenticated the same PR/head again.
For a single proposal, the API fixture observed two review-list reads and five
team-inventory reads. The outer approval adds no separate side-effect boundary.

Proposal PRs now obtain approval through each proposal's existing verifier.
Governed PRs without proposals retain their explicit approval check. Multiple
proposals still receive independent document, approval and packet validation.
Exact-head, current eligibility, canonical paths, merge-tree comparison and
submitter checks remain in force. No governed path is exempted.

Focused regressions establish one approval validation for a single proposal,
one for non-proposal governance, and one per proposal in a multi-proposal PR.
Dismissed/missing approval, a stale reviewed head and lost team membership or
permission still reject the PR before packet validation. Required source checks
and documentation checks continue to run. PR 265 merged after its protected
queue passed: run `40217942823` used 1,694 runner seconds and selected both image
validation jobs. The conservative classifier had not yet listed
`decision-check.py` as a host-only input. The initial source-only description was
incorrect. Its main run `40219479618` passed source checks, both image builds,
security scans and signing; qualification remains in progress at this report's
observation. The later classifier change explicitly covers this helper and
tests that host-only authority edits preserve image and qualification identity.

## Ordered follow-up

Delivery health and preparation reconciliation now share one runner setup and
one read-only inspection. The retained report includes the repository, checkout,
run, attempt and job identity; only that same job may consume it through
`--report`. Standalone reconciliation retains its original inspection behavior.
Reports are bounded regular JSON files and are replaced atomically. Failed
inspection removes any stale snapshot. Unhealthy reports still permit dispatch
when existing policy allows it; absent or mismatched snapshots cannot dispatch.
The inspector receives a read-only token, preparation receives the existing
scoped write token, and audit-health reporting runs independently. A final step
preserves each component's failure outcome. Neither current-main validation nor
duplicate/lost-response dispatch guards are cached.

The release policy now specifies a single manual approval on the exact release
proposal. Keep `environment: release` for signing secrets and main-only access;
remove only its migration-era required-reviewer rule. Package-cleanup approval
is unchanged. Apply the corresponding live setting only after this policy is
merged and no official release job is active or waiting. Capture the previous
setting, change only the reviewer requirement through the existing administrator
session, then run the read-only repository audit. If a release is active or the
setting cannot be changed, retain the existing hold and report the pending
activation; do not cancel or unblock an existing execution implicitly.

Authority event processing now resolves bounded PR/head/queue targets in a cheap
trusted-main discovery job without Nix or App credentials. The App workers are
serialized by repository, PR and target SHA, with one active and only the newest
pending worker. Running writers are not cancelled. PR heads and queue SHAs are
separate targets; review edits and dismissals still generate fresh evaluation.
Workers reauthenticate collector provenance and current PR state. Changed heads
are reported obsolete without posting, and a replaced queue ref cannot receive
a late result. Metadata failures never generate a success check. The original
batch CLI remains available; target discovery and explicit worker arguments are
additive interfaces.

## Exact-commit source proof

The prototype defaults to `FINITE_SOURCE_PROOF_REUSE=off`. Only native main-push
source checks may consume a proof. PR, protected queue, scheduled and manual
checks execute the full pinned aggregate. Queue execution adds a versioned
configuration fingerprint to its existing source receipt after the exact clean
checkout is verified. The fingerprint binds locked inputs, the actual Nix and
Python executables and versions, selected Nix settings, public CI options and
the Linux/X64 runner label. Selected configuration values are hashed; raw Nix
configuration and access tokens are never retained. The reuse control itself is
excluded so a shadow consumer can compare with a full queue producer.

A consumer has one 15-second process-group budget for configuration inspection,
native metadata, transfer, hashing and cleanup. It accepts only a completed,
successful native queue workflow for the exact commit, completed before the
consumer was created and no more than 24 hours old. Repository IDs, workflow,
run, attempt, source job, artifact origin and ZIP digest must agree. The ZIP is
bounded to 2 MiB, with bounded members. Both receipt phases must show successful
executed evaluation/build attempts within the native job interval. Missing,
failed, malformed, expired, interrupted or ambiguous evidence falls back to the
full checks. A configuration difference is a known ineligible result; unavailable
verification remains unknown rather than being counted as a cache miss.

`shadow` always executes the full aggregate and records whether its derivation
matches the authenticated producer. Only `enabled` may skip those two source
phases after successful verification. Its separate consumer receipt records
lookup cost and immutable producer references, with no invented evaluation or
build timings. The read-only cost report counts unique native jobs across retry
projections and exposes shadow matches, mismatches, enabled hits and unknown
coverage. The historical source-repetition diagnostic remains observational;
its recorded-input matches do not establish reuse eligibility or savings.

Collect five successful natural shadow comparisons before enabling a canary.
Do not generate commits or full VM rounds merely to fill that cohort. Confirm
there are no unresolved mismatches, retain full fallback and compare complete
source-job cost, including setup, lookup, retention and cleanup. Keep the mode
in shadow while evidence is incomplete; `off` immediately disables consumption.
Source proof grants no release approval or publication authority. Fresh source,
security, signing, reservations and publication boundaries remain independent.

Local validation passed 302 focused regressions, documentation checks,
actionlint and offline zizmor (no medium or high findings). Coverage includes
forged origins, changed products/evidence, missing or invalid receipts,
interrupted lookups, failed producers, fallback, partial timings, retry
accounting, approval revocation, stale authority, reservation contention,
lost responses and partial publication. Hosted pinned aggregate verification
is required before rollout.

| Work | State | Acceptance |
| --- | --- | --- |
| Consolidate proposal approval | Merged; protected queue passed, main qualification running | Observe the protected check on normal proposal/governance events. |
| Share delivery-health setup | Implemented; awaiting hosted rollout | One setup and one inspection, same-run snapshot reuse, independent failure reporting and live dispatch guards. |
| Remove migration release approval | Implemented policy; awaiting reviewed activation | One manual release-proposal approval; retain the environment, secrets, main-only access and fresh signing/publication checks. |
| Coalesce authority workers | Implemented; awaiting hosted rollout | One active and newest pending worker per PR/target, with fresh state and obsolete-target rejection. |
| Exact-commit queue source proof | Implemented prototype; default off, awaiting hosted checks | Bounded authenticated lookup, full fallback, five natural shadow matches before a canary. |

Use recent runs without waiting for October 30. Preserve historical reports and
frozen executions. No local Nix evaluation/build, image or VM run was used.
Metadata-only Nix configuration inspection used a 128 MiB limit and peaked at
20.9 MiB. Automatic Cachix writing and Grype database transport remain disabled.

## First main shadow lookup, October 26 UTC

PR 269 merged after [queue 40251210093](https://github.com/closure-labs/finite/actions/runs/40251210093)
passed both required local VM profiles. Its
[main run](https://github.com/closure-labs/finite/actions/runs/40255341966)
passed using 492 runner seconds, followed by successful natural controller and
delivery-health runs. Shadow lookup took 6.581 seconds and returned unknown
eligibility with `lookup-unavailable`; the complete aggregate still ran. This is
zero successful shadow comparisons, not a cache miss or a verified match.

The source job declared `actions: read` but its consuming step supplied neither
`GH_TOKEN` nor `GITHUB_TOKEN`. The initial workflow regression did not cover that
credential wiring. An authenticated read-only replay verifies the exact native
producer, source job and immutable artifact. That replay uses the retained
producer configuration and does not establish the missing consumer comparison.
It is diagnostic evidence, not an adoption sample.

The correction supplies the existing short-lived `github.token` only on the
source-check step for Finite's native main pushes. Job permissions remain
`contents: read` and `actions: read`; other events receive an empty value and
still execute full checks. The token is not added to job or workflow environment
scope, persisted in receipts or included in the configuration fingerprint.

If neither supported token variable is present, lookup now reports
`lookup-auth-unavailable` immediately, before configuration inspection or API
requests. Eligibility and hit remain unknown and full checks run. Queue producer
configuration capture still works without consumer credentials. Read-only cost
accounting retains this unknown reason rather than converting it to a miss.

Keep repository mode in shadow while the correction rolls out. Five natural
successful comparisons, with no unresolved mismatch, remain required before an
enabled canary. The independent [recent findings draft](https://github.com/closure-labs/finite/pull/270)
retains its original census while current main is integrated for governed-tree
review. No initialization,
installer, guest behavior, release approval or publication rule changes here.
