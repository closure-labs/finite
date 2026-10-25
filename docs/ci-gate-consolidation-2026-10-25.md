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
and documentation checks continue to run; this host-only change selects no
image or VM work.

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

| Work | State | Acceptance |
| --- | --- | --- |
| Consolidate proposal approval | Implemented; awaiting hosted rollout | Observe the protected check on normal proposal/governance events. |
| Share delivery-health setup | Implemented; awaiting hosted rollout | One setup and one inspection, same-run snapshot reuse, independent failure reporting and live dispatch guards. |
| Remove migration release approval | Implemented policy; awaiting reviewed activation | One manual release-proposal approval; retain the environment, secrets, main-only access and fresh signing/publication checks. |
| Coalesce authority workers | Planned | One active and newest pending worker per PR/target, with fresh state and obsolete-target rejection. |
| Exact-commit queue source proof | Planned; default off | Bounded authenticated lookup, full fallback, five natural shadow matches before a canary. |

Use recent runs without waiting for October 30. Preserve historical reports and
frozen executions. No local Nix, image or VM run was used. Automatic Cachix
writing and Grype database transport remain disabled.
