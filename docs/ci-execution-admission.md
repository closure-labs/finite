# Trusted pull-request CI execution

The [reviewed execution policy](../automation/github/ci-execution.json) permits
Decider and current Super Admin authors to start CI automatically for draft and
ready PRs. This applies to GitHub's fork-workflow execution approval only.
Human merge review, protected queue checks and publication authority retain
their existing rules. A stale human-review result can be refreshed through the
[approval recheck](approval-recheck.md) action. The worker never submits a PR review, posts a successful
check, enables auto-merge, approves an environment or publishes a product.

Ordinary PR checks already run without waiting for the maintainer decision
check. The [admission workflow](../.github/workflows/ci-run-admission.yml) handles
an actual GitHub `action_required` run when that execution approval is needed.
Other contributors retain GitHub's existing approval requirement. No repository
or organization fork-approval setting is relaxed.

## Authenticate the author and current execution

The controller reads only native GitHub metadata and checks out trusted `main`.
It never checks out or runs PR code, reads PR artifacts, follows a PR-provided
script path or supplies its token to a validation job.

Decider's immutable GitHub user ID and bot login are pinned in policy. The
credentialed worker also checks the App slug returned by token creation and
the configured App ID/login. Super Admin authors require the pinned team's
current immutable membership identity, active membership and maintain/admin
access to this repository. Maintainer-team membership or repository admin
access outside Super Admins does not grant this exception. Membership/API
failures leave execution unapproved.

Each run must belong to the reviewed Build Finite, CodeQL or decision-event
collector workflow, target this repository, and match the open main-targeting
PR's exact head SHA, source repository ID and branch. Native workflow identity
and active state are checked. Missing fork-run PR associations are resolved
through native commit associations; ambiguous origins fail closed.

Draft and ready PRs use the same authorization. Opening, pushing, reopening or
changing draft state triggers a cheap read-only discovery. An empty inventory
starts no Nix setup or App worker. A native blocked-run completion also triggers
discovery, covering a run created after the initial PR event. Successful normal
CI completions do not start a discovery runner.

Immediately before each approval, the worker reads live identity, PR head,
run attempt and approval state again. A moved or closed PR, changed author,
revoked membership, mismatched attempt, unknown metadata or different workflow
cannot be approved. Already running, completed-failed and environment-waiting
runs are left alone. The only mutation is the native Actions run's `/approve`
endpoint. Mutations are not retried; an uncertain response is reconciled by
reading the native state. An unresolved result fails without a second POST.
Workers for the same PR/head are serialized without cancelling a running writer.
Each worker re-scans the complete current blocked set, so replacing an older
pending worker cannot strand its workflow when a newer event arrives.

The Decider App already has Actions write permission. This worker requests only
Actions write and contents/PR/members read, using the existing SecretSpec
`review-app` scope. It receives no PR write, checks write, environment approval,
package publication or signing capability. Normal draft/ready transitions scan
for blocked runs; they do not rerun successful validation.

GitHub documents [fork workflow approval](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/approve-runs-from-forks)
and the [Actions execution approval endpoint](https://docs.github.com/en/rest/actions/workflow-runs#approve-a-workflow-run-for-a-fork-pull-request).
Actual blocked-run execution remains rollout evidence to collect naturally;
fixtures establish authorization boundaries without creating extra fork or VM
runs just to populate a report.

## Hosted fixture correction

The first hosted aggregate for [PR 272](https://github.com/closure-labs/finite/pull/272)
failed in an older release-origin test. Its fixture regenerated the same claimed
immutable ZIP with wall-clock timestamps. Crossing ZIP's two-second timestamp
boundary changed its digest between the initial download and staged reuse.
The fixture now uses a fixed ZIP member timestamp, with a clock-boundary
regression. Production archive authentication and release transport are
unchanged. This change is stacked on #272 for one combined protected validation.
