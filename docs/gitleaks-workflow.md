# Repository secret scanning

Every pull request and merge group runs the real `Repository security audit`
job (`repository-secrets`) in `Build Finite`, including documentation-only
changes. The existing native required `CI gate` depends on that job and requires
success. Missing, skipped, cancelled or failed scans block the gate. No new
repository setting, status publisher, App credential or authority controller is
needed. Historical auditing cannot satisfy this dependency.

This adapts the validated [XO #206](https://github.com/closure-labs/xo-nixpkg/pull/206)
implementation at `494fe1170e896f9bd9a57554e34ad61f507a99e2`. Its exact-head
Actions-owned scanner and CI gate, CodeQL and maintainer authority passed;
GitHub reported clean merge eligibility when inspected. The upstream
[Gitleaks CLI](https://github.com/gitleaks/gitleaks/tree/v8.30.1) is pinned to
8.30.1 and official Linux x64 archive SHA256
`551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`.

## Finite-specific integration

Finite already admits the native `build.yml` PR execution by immutable
repository, workflow, branch and current head. Keeping the scan inside that
execution covers ordinary contributors and Dependabot without extending the
execution-approval allowlist. Existing author, reviewer and execution-approval
requirements still apply. The scanner uses only `contents: read`, no candidate
scripts or local actions, no persisted checkout credentials, secrets, write or
OIDC grants. Governance already covers both the workflow and gate implementation.

The gate consumes GitHub's same-run `needs.repository-secrets.result`, rather
than searching for another run by name. An unrelated workflow, historical job,
saved success or stale head cannot supply that dependency. The native required
check remains `CI gate`, whose success now includes the actual scanner job.
This is not a synthetic successful scanner status or a settings bypass.

Unlike XO, Finite has no protected-base scanner config to preserve. The workflow
writes a fixed temporary config extending all upstream default rules; no custom
allowlist is introduced. Candidate `.gitleaks.toml`, `.gitleaksignore` and inline
allow comments cannot weaken it. This also permits initial rollout without a
separate config bootstrap. Workflow changes remain subject to existing exact-tree
governance and human authority.

## Incoming scope and failures

PRs scan `base.sha..head.sha`; merge groups scan `base_sha..head_sha`. Both use
the exact incoming head checkout, full history and all-parent traversal.
`--diff-merges=first-parent` changes merge diff presentation, not traversal;
side-branch commits, subsequently deleted additions and merge-only additions
remain in scope. Diverged PR bases are supported; queue bases must be ancestors.
Invalid, missing, shallow, unrelated or wrong-checkout inputs fail before scanning.
External diff and text conversion commands are disabled.

Findings, engine errors and the 600-second scan timeout fail closed. Output is
fully redacted and scanner stdout/stderr are discarded; only a fixed message and
numeric exit status are emitted. No findings payload or report is uploaded.
There is no baseline, size-based omission or fallback to a different range.

## Explicit historical tradeoff

The separate daily/manual `Audit repository secret history` workflow fetches
branch, tag and PR refs and scans all reachable history. It runs only on main;
its real `Repository historical audit (nonblocking debt)` job fails on findings,
errors or timeouts. Such failures remain visible and unresolved.

As explicitly accepted for XO #206, historical findings are nonblocking debt:
they do not prevent new merges or releases. This does not certify history clean,
remediate an old credential or waive findings newly introduced by a PR. Finite's
prior audit recorded public-key-fingerprint matches in historical policy data;
the new full-history audit has not yet run. Full default rules may also identify
new false positives, which still block incoming scans until specifically reviewed.

This change adds a premerge requirement; it does not retrofit scanner receipts
onto already merged revisions or alter existing release, signing, approval,
credential or native scanning/push-protection boundaries. It does not import
XO's separate publication-observation architecture into Finite.

## Validation and publication

Lightweight fixtures exercise Git ranges, malformed origins, exact job naming,
native gate failure propagation, ordinary and Dependabot PR origins, and
read-only wiring, actual shallow clones, unrelated histories and trigger guards.
A cached Gitleaks 8.30.1 binary additionally verifies a tiny
synthetic history: an old finding is outside the incoming range, a new finding
blocks despite candidate config/ignore files and an inline allow comment, and
deleting it later does not hide it.
No laptop builds or repository-wide history scan are needed.

Hosted validation must still confirm the checksum-pinned download and actual
GitHub check names/conclusions for the published head. Publication is pending
explicit approval: push only this dedicated branch, open a separate PR against
current main, then inspect exact-head scanner, required gate, CodeQL and
authority results. Do not merge or change settings as part of publication.
