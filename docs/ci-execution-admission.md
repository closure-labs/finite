# Trusted pull-request CI execution

The [reviewed execution policy](../automation/github/ci-execution.json) permits
Decider, current Super Admin authors and verified official Dependabot Actions
pin updates to start CI automatically for draft and ready PRs. PR readiness is
left unchanged. This applies to GitHub's fork-workflow execution approval only.
Human merge review, protected queue checks and publication authority retain
their existing rules. A stale human-review result can be refreshed through the
[approval recheck](approval-recheck.md) action. The worker never submits a PR review, posts a successful
check, enables auto-merge, approves an environment or publishes a product.

Ordinary PR checks already run without waiting for the maintainer decision
check. The [admission workflow](../.github/workflows/ci-run-admission.yml) handles
an actual GitHub `action_required` run when that execution approval is needed.
Official Dependabot pin updates qualify after the
[immutable dependency classifier](dependency-review.md) passes. Execution does
not require a human review; merging still requires current-head human approval.
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

Each run must belong to a reviewed PR CI workflow. The decision-event collector
also permits native `pull_request_review` executions, so an execution hold cannot
strand a late review before authority validation. Other review-triggered,
manual, schedule, merge-group and publication runs are excluded. Runs target this repository, and match the open main-targeting
PR's exact head SHA, source repository ID and branch. Native workflow identity
and active state are checked. Missing fork-run PR associations are resolved
through a bounded native open-PR lookup by source owner and branch. Each result
must still match the full source repository ID/name, branch, exact head and
open main-targeting PR. Commit associations can also be empty for an open fork,
so they are not used as a prerequisite. Ambiguous or unavailable origins fail
closed; the lookup never grants author trust.

Draft and ready PRs use the same authorization. Opening, pushing, reopening or
changing draft state triggers a cheap read-only discovery. An empty inventory
starts no Nix setup or App worker. A native blocked-run completion also triggers
discovery, covering a run created after the initial PR event. A successful
review-event collector also re-scans blocked runs, so a later human review does
not depend on another blocked-run event. Successful ordinary CI completions do
not start a discovery runner. A completed trusted-main authority workflow also
reconciles blocked official dependency PRs as bounded recovery; its success
never supplies approval, and the worker verifies live bot identity and the
complete pin delta again.

Immediately before each approval, the worker reads live identity, PR head,
run attempt and approval state again. A moved or closed PR, changed author,
revoked membership, mismatched attempt, unknown metadata or different workflow
cannot be approved. After the final dependency classification, the worker
re-reads the exact run ID, workflow ID/path, attempt, head and source branch
before posting. Event sender, run actor and triggering actor never substitute
for the live PR author. Already running, completed-failed and environment-waiting
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

## Current-base execution binding

A PR run executes a synthetic merge, while the pin classifier compares the
merge base with the PR head. Those are different sources when main has
advanced independently. A main-only workflow job or local-action change could
therefore escape classification even though the final author/head/run checks
pass. This is an admission-validation gap; it is not evidence of exploitation,
a disclosed secret or a write token actually issued by GitHub.

Official Dependabot execution now requires its classified base to equal the
live native `refs/heads/main` commit, and its merge base to equal that base.
Thus current main must already be included in the PR head. A clean merge of
that base adds no unseen executable changes to the head. A stale or diverged
branch must be refreshed before this automatic execution exception applies;
no human execution review is substituted for that proof.

The worker rechecks the live main ref after classification and once more after
the final native run read, before its sole approval POST. The initial PR base
must remain unchanged across validations. Missing, malformed, unavailable or
moving main evidence fails closed. Existing PR/head/source/run/workflow/attempt
checks and current-head human merge approval remain in force. GitHub offers no
atomic head/base/attempt condition on its approval endpoint, so these are live
revalidation checks rather than a claim of an atomic transaction.

Real Git fixtures create divergent main-only workflow and composite changes,
verify they survive a clean synthetic merge and pin classification, and require
execution admission to reject them. Refreshed heads, including a harmless main
update, pass. The ancestry guard closes the unseen-base divergence gap; it is
not a general privilege scanner for unsafe code already trusted in current
main. The ordinary PR permission audit below remains a separate requirement.

## Unprivileged PR execution

The admitted workflows are Build Finite, CodeQL Advanced and the metadata-only
decision-event collector. Their native `pull_request` triggers run on opening
and synchronization, including draft PRs, without depending on another event.
The controller only releases precisely bound `action_required` runs through the
existing restricted App token. It does not dispatch replacement validation.

Build's PR jobs use contents/Actions/PR reads, checkout without persisted
credentials, and no secrets. The ordinary PR still executes documentation and
selected Nix/runtime checks, and `CI gate` requires those selected jobs to
succeed. Image assembly is excluded by `event_name != 'pull_request'`;
publication also requires this repository, the main ref and a push, schedule or
manual event. The optional VM-tools benchmark is branch-limited and read-only.
The setup-nix composite receives no merge-queue token, disables installer OIDC,
and saves shared caches only from main push/schedule/manual runs. PR caches
remain subject to GitHub's native ref isolation.

CodeQL PR analysis explicitly requests contents read only, has no secrets and
uses `build-mode: none`. GitHub permits native `pull_request` code-scanning
uploads without a security-events write token, including for Dependabot
([GitHub documentation](https://docs.github.com/en/code-security/reference/code-scanning/troubleshoot-analysis-errors/resource-not-accessible)).
Its existing `Analyze (actions)` and `Analyze (python)` PR check names and result
categories remain intact. The separate non-PR job retains security-events write
for main analysis and uses distinct `Analyze branch (...)` names so a skipped job
cannot supply a successful result for the PR's required analysis context.
The decision-event collector has contents read only and executes a fixed echo;
it never checks out candidate code. None of these PR jobs receives the
controller's App token, signing keys, publication secrets or write permissions.

The full pin classifier remains shared with merge authority, unchanged. Only
execution admission omits `authority.approval`; decision-check still validates
current-head human review and eligibility. Unsupported changes and outsiders
retain their existing admission behavior. Fixtures exercise both draft and
ready execution without reviews, independent merge denial, spoofed identity,
forks, moved heads/bases, altered workflows, and exact run/attempt binding.
Hosted CodeQL reporting and native held-run release remain rollout evidence to
collect after publication is authorized; local fixtures do not claim hosted
execution evidence.

## Hosted fixture correction

The first hosted aggregate for [PR 272](https://github.com/closure-labs/finite/pull/272)
failed in an older release-origin test. Its fixture regenerated the same claimed
immutable ZIP with wall-clock timestamps. Crossing ZIP's two-second timestamp
boundary changed its digest between the initial download and staged reuse.
The fixture now uses a fixed ZIP member timestamp, with a clock-boundary
regression. Production archive authentication and release transport are
unchanged. This change is stacked on #272 for one combined protected validation.

## Fork-origin lookup evidence

A [read-only native snapshot](ci-fork-origin-2026-10-26.json) records an open
[public fork PR](https://github.com/cli/cli/pull/14816) whose
[workflow run](https://github.com/cli/cli/actions/runs/40157926064) has an empty PR
association list. Its commit-to-PR lookup is also empty at the recorded head.
The source owner/branch query identifies that exact open PR, and its source
repository ID, branch and head match the native run. This is metadata lookup
evidence; Finite's pinned Decider or live Super Admin authorization still runs
independently before any execution approval.

The current lookup rejects missing source identity, ambiguous or oversized
results, changed heads, mismatched source repositories and unavailable metadata.
An existing explicit PR association is still authenticated directly. Source
branches are URL encoded, never inserted into shell commands. The reconciled
blocked-run inventory also includes review-event collectors, so replacing an
older pending worker cannot strand a late-review collector. Other review
workflows and manual, schedule, merge-group or publication runs remain excluded.
