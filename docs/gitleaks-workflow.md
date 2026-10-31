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
requirements still apply. Gitleaks executes no candidate scripts or local actions,
and receives no persisted checkout credentials, secrets, write or OIDC grants.
The job additionally grants `actions: read` only for protected-base payload
authentication; its API token is not passed to Gitleaks. Governance already covers
both the workflow and gate implementation.

The gate consumes GitHub's same-run `needs.repository-secrets.result`, rather
than searching for another run by name. An unrelated workflow, historical job,
saved success or stale head cannot supply that dependency. The native required
check remains `CI gate`, whose success now includes the actual scanner job.
This is not a synthetic successful scanner status or a settings bypass.

Unlike XO, Finite has no protected-base scanner config to preserve. The workflow
writes a fixed temporary config extending all upstream default rules. Candidate
`.gitleaks.toml`, `.gitleaksignore` and inline allow comments cannot weaken it.
This also permits initial rollout without a separate config bootstrap. Workflow changes remain subject to existing exact-tree
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

## Verified inherited finding identifiers

The incoming audit can suppress only `generic-api-key` fingerprints for generated
`payload.findings[].key` identifiers in content-addressed
`automation/decisions/security/<sha256>.json` packets. A packet must be a regular
Git blob byte-identical to the trusted main event base of `closure-labs/finite`,
have the exact version-1
`security-findings` envelope, and match its canonical content-addressed filename.
Each identifier is independently recomputed from `profile`, `component`,
`advisory`, and `exposure`; a field label or 64-character hex value is insufficient.

Workflow-owned standard-library code runs under isolated Python (`-I`), without
importing candidate modules. It rejects duplicate/ambiguous JSON and requires the
controller's pretty-printed encoding. Equal-length markers locate only validated
JSON paths. An exception names one commit, packet path, rule, and line, and that
line must contain only the exact identifier field. Minified or shared lines get
no exceptions. New/modified candidate packets get no inherited exceptions.
Arbitrary hashes, other JSON paths and credentials elsewhere in the same packet
remain fully scanned. No packet,
file, commit, or history range is excluded; all other default rules remain active.
The historical audit is unchanged. These hash checks grant no decision authority.

This handles base history reappearing in first-parent merge diffs without turning
known packet files into a secret-scanning exclusion. The generated exception file
exists only in runner temporary storage; findings and exception payloads are not
logged or uploaded. Generator or scanner errors fail the native gate closed.


## Authenticated new packet identifiers

A separate protected-base verifier may grant exact `generic-api-key`
commit/path/line exceptions for one new immutable security packet in an incoming
range. Revocations retain their existing full scan and separate authority gate;
they receive no new exceptions or new authentication gate. It never imports PR code. The verifier and all authentication helpers are
loaded from the exact GitHub event base checkout; an older base lacking the
verifier grants no new exceptions. The read-only Actions token belongs only to
that verifier step, not Gitleaks. No review, risk acceptance, signing or release
authority is granted by this operation.

The verifier reuses `decision_controller.validate_proposal_packet`: live native
producer repository/workflow/source/run/attempt, source ancestry in protected
main, exact artifact identities/digests, OCI manifest/layer hashes and canonical
request hash, both downloaded Actions ZIP sizes/digests, complete matching native
file inventories, and reevaluated normalized findings must all agree. Metadata
alone cannot grant an exception. Canonical JSON, duplicate rejection, complete
finding identity recomputation and equal-length structural markers restrict each
exception to the standalone `payload.findings[].key` field.

The new path is bounded to one immutable packet, a 2 MiB proposal document,
128 OCI members, 1,538 MiB of OCI payload including its manifest, and a 600-second
authentication timeout. Existing tighter native ZIP/member/expansion limits still
apply. Authentication failure clears the new receipt and fails the job; the full
Gitleaks scan still runs. Existing inherited-base semantics, scanner pin,
complete history range, default rules and credential redaction are unchanged.

The dedicated read-only fixture workflow checksum-pins the same real Gitleaks
engine and exercises genuine secret signals, forged provenance/IDs, modified ZIP
and OCI bytes, duplicate/minified/relocated fields and path spoofing without
network authentication. The actual #345 payload was also independently fetched
and authenticated: 34 native files matched, all 596 IDs recomputed, and its 593
generated-ID detections were precisely covered. #345 itself is untouched. Its
old event base cannot gain this behavior from a stale rerun; the policy must be
reviewed/merged and fresh validation bound to a base containing the verifier.

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
A cached Gitleaks 8.30.1 binary additionally verifies tiny synthetic histories
for inherited recomputed IDs, wrong IDs, new/modified packets, duplicate/minified
JSON, path and field relocation, adjacent credentials, and candidate Python
module shadowing. The default-engine range fixture proves that an old finding
is outside the incoming range, a new finding blocks despite candidate config/ignore files and an inline allow comment, and
deleting it later does not hide it.
No laptop builds or repository-wide history scan are needed.

Hosted validation must still confirm the checksum-pinned download and actual
GitHub check names/conclusions for the published head. Publication is pending
explicit approval: push only this dedicated branch, open a separate PR against
current main, then inspect exact-head scanner, required gate, CodeQL and
authority results. Do not merge or change settings as part of publication.
