# Security decision contracts

`security_decisions.py` compares validated native scan observations with findings from an independently authenticated human decision. It does not establish approval authority. Passing scanner policy, an AI applicability assessment, a JSON `reviewedBy` field, a label, and a merged file grant no permission by themselves.

## Findings admission

Call `evaluate(scan_result, profile, accepted=None, revoked=False)`. Supply `accepted` as a normalized findings list from an authorized decision; `None` requires initial approval, even for an empty scan. An authenticated empty list covers subsequent empty scans.

During bootstrap, the controller reevaluates authenticated native bytes using a strictly validated projection of the checked policy's native-health fields. This produces the same severity and CVSS ceilings as the later maintainer mode, while leaving the checked policy mode and publication enforcement unchanged. Legacy AI dispositions and holds cannot suppress observations or grant approval.

The scan must contain its complete `observations` array. A native `complete` result additionally requires `scannerHealth: healthy`; `admissionSeverity` carries the highest primary or related severity when supplied. Each observation requires a versioned package URL or opaque artifact ID bound to the immutable scanned image, advisory and aliases, severity, boolean `knownExploited`, complete canonical absolute shipped-file locations, and fix versions. Optional `cvss` accepts a numeric base score or Grype CVSS records. Scanner errors, missing observations, unbound opaque identities, incomplete exposure and lost previously known CVSS evidence are technical errors.

Normalized identity uses profile, unversioned package URL (retaining namespace, qualifiers and subpath), canonical CVE, and exposure. Opaque artifact IDs bind to the exact image digest and require a new review when that digest changes. Multiple CVEs are separate occurrences; advisories without CVE aliases retain their primary advisory identifier. The comparison groups the same profile/component/CVE to detect exposure expansion. All severities, including unknown, require review when newly introduced. Increased severity or CVSS, new known exploitation and expanded exposure require review. Package versions, image digests and available fixes remain provenance/information; changes alone do not invalidate acceptance. Reduced risk, reduced exposure and resolved findings carry acceptance forward. Version-specific applicability must still be revalidated by the packet producer; this module does not infer equivalent applicability from a package name.

CLI:

```console
python3 scripts/ci/security_decisions.py --scan security-result.json --profile finite --accepted authenticated-findings.json --output admission.json
```

Exit codes: `0` covered, `3` human decision required or revoked, `2` technical failure. The output includes the normalized findings and added/worsened/unchanged/improved/resolved comparisons.

## Authoritative human decision

A proposal has exactly `schema`, `kind` and `payload`. Hash the entire document using UTF-8 JSON with sorted keys, compact separators and no nonfinite numbers. The proposal does not include its own hash, PR number or later approval receipt. The path is `automation/decisions/security/<hash>.json` for security decisions and `automation/decisions/releases/<hash>.json` for a release set.

Security payloads contain both profiles' normalized findings, a content-addressed evidence packet reference and producer identity, disposition (`accepted`, `rejected`, or `revoked`), and rationale. Release-set payload semantics are independently validated by release preparation. Evidence provenance and applicability are validated by the controller before it asks for approval; authority verification validates the review boundary, not scanner correctness.

`decision-authority.py` requires a configured trusted GitHub App bot login. The configured App, active `closure-labs/maintainers` members and active `closure-labs/super-admins` members may submit same-repository main-targeting proposals. Human submitters require current write, maintain or admin repository access and pinned team identities (Maintainers `20196828`, Super Admins `20196962`). It verifies PR identity; the exact proposal at the current reviewed PR head; allowed changed paths; an active `closure-labs/super-admins` member's human approval on that exact head; current maintain/admin reviewer permission and pinned team membership; absence of later unresolved eligible changes requests; and, for runtime authorization, merged state, identical proposal in the merge commit, merge ancestry of current main and unchanged proposal on current main. It derives the origin PR from file commit history when no PR is supplied. Renames, deletions, missing pagination, API failure and changed PR state fail closed. Governed code and workflow PRs use the same submitter and Super Admin approval restrictions; ordinary PRs keep their existing checks.

```console
python3 scripts/ci/decision-authority.py --proposal proposal.json --repository closure-labs/finite --bot-login 'cl-decider[bot]' --output authority.json
```

`--pr` supplies a PR number for a premerge check or explicit lookup. `--allow-open` is for PR/merge-queue validation only and must never authorize publication. Additional report files must be explicitly allowed with `--allow-path`; code changes are not implicitly allowed in a decision proposal. Exit code `0` means authenticated authority, `2` means no usable authority.

Before selecting an active decision and again before returning admission, the controller authenticates the complete current-main security ledger through an untruncated Git tree. The canonical record set must match the local checkout, including an empty ledger. New revocations, supersessions, deletions, malformed paths or API errors fail closed until the checkout is refreshed. Main advances that leave the ledger unchanged remain valid.

Super Admins may approve their own PRs. GitHub prohibits an author from
submitting an Approve review on their own PR, so use **Files changed → Review
changes → Comment** with exactly:

```text
/decider approve <full 40-character current PR head SHA>
```

Decider accepts this explicit Comment review only from a currently eligible
Super Admin and only when both the command and GitHub's review `commit_id`
match the current PR head. Maintainers outside Super Admins cannot approve,
including their own submissions. Plain PR comments, quoted commands, bots and
stale heads grant no authority. Normal Approve reviews from Super Admins remain
supported. The existing review-event collector rechecks the PR and merge queue.

To withdraw an explicit approval, submit a later Comment review containing
`/decider withdraw <full current PR head SHA>`. A later dismissal or eligible
changes-requested review also removes or blocks approval. Editing the command
away removes that approval on the next live authority check. Pushing a new head
requires a new approval. Super Admin membership and repository maintain/admin
access remain required at every publication boundary. Repository rules that
separately require native GitHub Approve reviews cannot be satisfied by a
Comment review; this change uses the required Decider authority check and does
not alter live repository rules.

Authority has no automatic expiry. Dismissing the qualifying review, a later unresolved changes-requested review, or removal from Super Admins or loss of maintain/admin permission invalidates it on the next check. The controller must additionally apply merged explicit revocations and prevent older decisions from overriding them. Every publication boundary rechecks authority; a cached or signed historical receipt cannot replace current API checks.

The controller must validate the proposal disposition before authorizing publication: an authenticated rejected or revoked proposal is an authentic human decision, not permission to publish. Community security tooling provides observations only and cannot approve decisions.

## Evidence retention and merge queue

Upload evidence as an OCI artifact in `ghcr.io/closure-labs/finite-decisions` and reference its immutable digest. Retain accepted scan packets and release packets indefinitely; mutable tags are discovery aids. Bind native scan files and their hashes to the trusted producer repository, workflow, source revision, run, attempt and GitHub artifact identity before uploading.

PR and merge-group required checks must execute trusted default-branch verification code and compare the proposal content of the synthetic queued tree with the exact approved PR head. Rebasing the queue may change commit IDs but must not change the canonical proposal hash. Prevent unreviewed changes to governed policy and decision-controller files through a separate required authority check. No approval receipt commit is needed.

## Reused native evidence

Optional `original-security-result.json` and `reuse-provenance.json` files remain bounded transport metadata. Their contents never establish human approval. Current valid native evidence may continue unattended when live human admission covers its findings.

An uncovered reused scan cannot become a new decision packet by assigning it the later transport run's timestamps. The controller requests one full, two-profile build without resume inputs to produce a fresh native snapshot. A failed fresh full build stops on its technical error; it does not trigger a consolidation loop. A covered single-profile resumed scan needs no additional build or review request.

The resume coordinator reconstructs the approved historical snapshot from its
native Grype evidence at the recorded scan time, including CVSS omitted by older
summary formats. This only selects build or rescan work. The publisher requires
fresh native health and live authority independently. The coordinator checks
admission's `decision.proposalHash` against the active leaf before claiming work
and again before dispatch.

## Proposing rejection or revocation

Dispatch **Reconcile maintainer decisions** on main. Select `rejected`, provide
a fresh complete `producer_run` and a rationale to propose rejection even when
an existing acceptance or pending acceptance proposal covers that scan. This
changes the proposed disposition only; an active Super Admin with maintain/admin access still reviews
and merges the exact approved proposal head.

Select `revoked`, leave `producer_run` empty, and provide the current accepted
`decision_hash` plus a rationale to withdraw an existing acceptance without
fresh scans or access to expired scan artifacts. The proposal copies the exact
accepted profiles, findings and immutable packet, and explicitly supersedes
that accepted leaf. The App check authenticates its canonical parent's bot merge
and rejects altered scope, findings, packet identity or a stale parent. The new
revocation itself requires current human approval; historical parent provenance
never grants publication authority. Dismissing an existing qualifying review
also withdraws that review's authority immediately on the next boundary check.

## Activating the human decision policy

After the required App check is live and a human has approved the initial
findings baseline, dispatch **Reconcile maintainer decisions** on main with
`operation: propose-cutover` and a complete, fresh two-profile `producer_run`.
Leave disposition accepted and rationale/decision hash empty. The controller
rechecks authenticated native health and current human admission for both
profiles before creating any branch or PR. Missing authority, expired native
health, incomplete producer evidence, or an unbound App check stops the request.

The App authors a draft PR that changes only
`automation/security/image-policy.json` to the exact native health fields and
`maintainer-decision` mode. It marks the PR ready and enables auto-merge; a
Super Admin with maintain/admin access must still approve that exact head. Creating the PR grants no
risk acceptance and does not remove release environment reviewers. This allows
a sole maintainer to review the App's proposal. An equivalent existing bot PR
is reused only after its complete file inventory, repository, head and policy
content are verified; divergent branches are never overwritten. Once the mode
is active, the command reports `already-active` and creates nothing.
