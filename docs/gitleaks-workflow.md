# Repository secret scanning

Every pull request and merge group calls `incoming-secret-scan.yml` from
`Build Finite`, including documentation-only changes. The existing
`Repository security audit` job (`repository-secrets`) preserves its status name
and succeeds only when that same run's reusable scan succeeds. The native required
`CI gate` still depends on it. Missing, skipped, cancelled or failed scans block
both statuses. No new
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
execution-approval allowlist. The reusable workflow has only `workflow_call`, no
identity inputs or inherited secrets; it uses the caller's exact event head/base.
Existing author, reviewer and execution-approval
requirements still apply. Gitleaks executes no candidate scripts or local actions,
and receives no persisted checkout credentials, secrets, write or OIDC grants.
The job needs only `contents: read`; finding-ID classification uses no API token
or registry download. Governance covers the workflow and gate implementation.

The compatibility job checks GitHub's native `needs.incoming-scan.result`
with no checkout or setup, then CI gate consumes `needs.repository-secrets.result`.
Its `always()` condition evaluates failed, skipped and cancelled scan results
instead of letting an implicit success condition skip the check. It runs only on
PR/merge-group events, as before. An unrelated workflow, historical job,
saved success or stale head cannot supply that dependency. The native required
check remains `CI gate`, whose success includes the actual scanner job.

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
These incoming hash checks grant no decision authority. The historical workflow uses the separate policy below.

This handles base history reappearing in first-parent merge diffs without turning
known packet files into a secret-scanning exclusion. The generated exception file
exists only in runner temporary storage; findings and exception payloads are not
logged or uploaded. Generator or scanner errors fail the native gate closed.


## New packet identifier classification is not risk acceptance

A protected-base classifier permits exact `generic-api-key` commit/path/line
exceptions for a new canonical content-addressed security packet. It parses the
complete JSON, validates the proposal structure, recomputes each finding key from
profile/component/advisory/exposure, and requires the key alone on its canonical
line. Duplicate JSON, forged keys, minified/shared lines, spoofed paths and other
credential locations still fail. It never imports candidate code, and an older
protected base without the classifier grants no new exceptions.

Secret classification does not need to download the producer's OCI packet and
both Actions ZIPs to determine whether a computed identifier is a credential.
Those operations duplicated the independent findings-acceptance verifier. The
scanner now performs the local semantic proof without `actions: read`, an API
token or an ORAS installation. It does not authenticate a claimed producer or
grant any authority. The unchanged maintainer decision authority and security
admission paths still authenticate producer payload bytes/source/run/attempt and
require exact findings-specific human acceptance. Fixtures deliberately classify
a generated ID under invalid producer metadata while proving the independent
producer verifier rejects that packet. There is no shared successful scan receipt
that can satisfy the risk-acceptance gate.

### Native allowlist tradeoff

Gitleaks supports a standard rule-specific AND allowlist combining packet paths
and a standalone 64-hex `key` line. The pinned 8.30.1 engine demonstrates that this
also hides an arbitrary non-generated hex API key on that line: a regex cannot
recompute the finding identity. That would be a classification blind spot even
without a tampering threat model. This draft therefore retains standard native
fingerprints generated only after the semantic check. Native allowlist config is
a negative fixture, not production policy. Full incoming/default-rule scanning,
separate historical scans and merge-group tests remain active. No file/range or
blanket hash exclusion is added.

See the pinned upstream [allowlist documentation](https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md#configuration).

## Historical finding-ID exceptions

The historical audit uses the standard upstream Gitleaks fingerprint ignore
mechanism for the same standalone generated finding IDs. Current-main tooling
calls the existing `finding_id_packets.proposal_lines` validator: complete packet
schema, duplicate rejection, canonical document filename/encoding, each finding's
recomputed identity and exact standalone line must all agree. The entire historical
packet Git blob must also be byte-identical to the regular blob at the immutable
protected-main audit source. The current field label, a plausible hash, source
ancestry or old packet filename alone cannot qualify. Removed or modified packets
retain their complete scan. No historical modules/configuration are executed.

`history_finding_ids.py` traverses every fetched ref/parent and computes first-parent
merge diffs just as the unchanged scan does. It writes only exact
commit/path/`generic-api-key`/line fingerprints, never packet/file/commit/range
exclusions. A different rule, another line, copied IDs outside the packet path,
forged/relocated IDs or a different blob at the same path remain scanned. This
recognizes generated identifiers, not security acceptance or publication authority;
live producer, risk acceptance, signature and promotion gates remain independent.

The helper is bounded to 20,000 commits, 100,000 fingerprints and the existing
2 MiB packet parser limit, with a 120-second wrapper and existing bounded Git
calls. Failure, malformed history, exhaustion or timeout stops the audit with no
clean receipt. It clears stale output before validation, uses mode 0600, and logs
only a fixed error. The existing 20-minute job cap, 600-second engine limit,
checksum-pinned default rules, full fetched history, raw-report deletion and
aggregate-only diagnostics remain intact. No new credentials or network API calls
are needed by the exception generator.

Preparation established that 18,317 protected-main historical detections were
canonical finding IDs in unchanged, validated main packets. That evidence supports
only the exact packet-ID policy above. Additional public-key hashes, fingerprints,
Git revisions and source-file checksums were investigated separately; this draft
does not add exceptions for those different contexts or blindly suppress matches
in older/unmerged packet blobs.

## Reproducible historical baseline

Each reviewed-main audit now preserves a native
`history-provenance-<run>-<attempt>` artifact containing only exact public ref
names/object IDs/types, the immutable checkout source, run/attempt, scanner version,
official archive checksum, complete log flags, effective config checksum,
and exception-policy version/checksum/count. Native public-identifier allowances
record their reviewed catalog digest and counts instead of uploading config values. The same ref snapshot
and source must still match after scanning. More than 20,000 refs or an 8 MiB
manifest fails closed; nothing is silently truncated. Ref object IDs capture the
scan inputs even if refs later move; replay still requires those Git objects to
remain available. No full repository bundle is uploaded.

The other artifact file contains fixed verdicts and aggregate counts only.
Remaining matches are categorized as fully validated canonical packet-ID lines
without a main exception, unclassified generic-key matches, or other default-rule
matches. Category recognition never waives a finding. Packet observation uses the
existing bounded parser with at most 256 distinct commit/path documents; a malformed
packet stays unclassified, while lookup/budget errors fail closed. No report fields,
matched values, snippets, arbitrary rule/path names or fingerprints enter the
summary. Raw temporary reports are still deleted, including on failure. Neither
raw reports nor the generated exception list are uploaded.

This establishes a fresh, ref-bound baseline. The old all-ref report did not retain
its ref set or detailed findings; it is not used as a clean baseline or reconstructed
by inference from counts. New unknown findings remain failures of the historical
job. The incoming required scanner and release/acceptance gates are unchanged.

Tiny real-engine fixtures cover canonical inherited IDs including first-parent
merges, actual synthetic credentials elsewhere in a packet, generic matches
outside its path, forged IDs, malformed/duplicate/minified/relocated packets,
wrong paths, untrusted-ref blob substitutions, removed packets and symlinks.
Wrong source, shallow history, resource exhaustion and stale-output failures are
also exercised. No repository-wide local all-ref scan or image build is required.

## Reviewed exact-identifier follow-up

The follow-up policy is limited to the 719 findings of baseline run
[41338989009](https://github.com/closure-labs/finite/actions/runs/41338989009):
593 recomputed IDs in one previously byte-authenticated packet, 120 parsed
public-key hashes/fingerprints, four public Git identifiers and two source-file
checksums. Its standard Gitleaks fingerprint file is linked by SHA-256 to a
reviewed proof catalog containing exact Git blob, whole-blob, line and identifier
hashes and immutable public-source bindings. The catalog stores fingerprint
digests instead of duplicating native fingerprint strings. No matched values,
key payloads or report snippets are added to the policy files.

The catalog is loaded only from the workflow's own reviewed main tooling, never
from a subject/historical checkout. The packet's raw blob is bound to the earlier
native payload-authentication receipt and the existing full packet/identity parser;
this does not accept its vulnerabilities or grant live publication authority.
Public-key and public-Git evidence was also preserved for offline review; old
native payload authentication was not silently rerun or replaced by a label.

The same reviewed 719-entry catalog now compiles to standard upstream
rule-specific allowlists before one complete scan. Every allowance uses native
`condition = "AND"`: the exact immutable commit, exact path, exact complete
verified public line, and the original rule must all match. Source blob, line,
identifier and canonical packet proofs remain checked before generation; a field
label or hash shape alone is insufficient. A different credential on the same
line changes the complete line and cannot match. Copied identifiers at new
commits remain findings. Upstream line-location handling permits only zero or
one preceding newline, not a multiline wildcard.

This replaces the preliminary full scan, custom redacted-match/column parser and
second fingerprint scan. The sole upstream scan still extends all default rules,
scans every fetched ref and parent, ignores candidate inline allows, and determines
the verdict. No commit or file is skipped. The original canonical-main packet-ID
fingerprints remain unchanged. Catalog entries outside the complete reachable
`--all` commit closure cannot match that scan and are counted as unused; frozen
validation instead requires all 719 entries to remain reachable and valid. Git
history errors or source-proof failures stop before scanning.

The version-2 ref manifest records the actual compiled-config SHA256, catalog
digest and counts. It does not upload the compiled config or public identifier payloads.
The prior frozen baseline manifest and its original default config/ID-ignore
bindings remain unchanged; a new validation records the reviewed policy change
rather than claiming its effective config is byte-identical to the old one.
The existing 20-minute job and 600-second engine caps remain. This removes one
full pass; a wall-clock improvement has not been measured.

## Same-recorded-ref validation

Manual dispatch offers the fixed `baseline-41338989009-1` snapshot (the default)
or `current`; scheduled audits retain current full fetched history. The fixed
snapshot's checked-in ref/config manifest must match the byte-authenticated native
artifact digest. The preparation helper fetches only its explicit object IDs into
a new isolated subject repository, restores exactly its 393 refs and detached
subject HEAD, and verifies completeness. No moving branch/tag/PR enumeration,
shallow truncation, historical checkout execution, alternate source or fallback
to current history is permitted. Missing objects or mismatched refs fail closed.

Before the sole scan, the original canonical-ID ignore digest must still equal
the recorded baseline. Scanner archive, version, default rule coverage and log
flags stay identical. The added native allowances have a new effective-config
digest, explicitly recorded alongside the reviewed catalog and all 719 successful
source proofs. This is a policy transition, not a claim that the effective config
is the old literal default config. Additional unknown matches remain findings.
The artifact separates subject revision from reviewed tooling revision, records
the reference manifest digest, and retains the native final summary. The temporary
raw report is deleted on exit and is never uploaded. Earlier two-pass validation
artifacts remain historical evidence; new runs need no first-pass verification
receipt or report parser.

Validation uses pinned real-engine synthetic histories for same-line multiple
matches, provider rules, copied IDs, changed commits, malformed source lines,
wrong byte/line/value bindings, effective-config manifests and shared packet validation.
Local frozen-ref fixtures prove exact reconstruction, no historical-file checkout,
missing-object failure and original-ignore mismatch. Full frozen validation occurs
only through the guarded reviewed-main workflow; it is not an extra moving-ref
repository scan or a production dispatch.

## Explicit historical tradeoff

The separate daily/manual `Audit repository secret history` workflow fetches
branch, tag and PR refs and scans all reachable history. It runs only on main;
its real `Repository historical audit (nonblocking debt)` job fails on findings,
errors or timeouts. Such failures remain visible and unresolved.

As explicitly accepted for XO #206, historical findings are nonblocking debt:
they do not prevent new merges or releases. This does not certify history clean,
remediate an old credential or waive findings newly introduced by a PR. The full-history audit at source
`5a6abff84027a6e3202e2b3c3e31520781543819` reported 20,228 generic-key
matches and two other-rule matches. Separate bounded investigation proved those
two other-rule matches were one public Git revision in documentation; this draft
does not suppress them or certify the remaining history. Full default rules may
identify additional false positives, which still block incoming scans until
specifically reviewed.

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


## Shared upstream installer rollout

The credential-free fixture job and protected-main historical job share the
`setup-gitleaks` composite action, preserving the exact 8.30.1 archive checksum,
HTTPS restriction, transfer timeout and version assertion. A failed download or
checksum stops before extraction/execution. No new action dependency, license,
credential, scanner configuration or cache is introduced.

After #367 merged, incoming scanning also uses the one shared script. Its
protected-base checkout now precedes installation and is bound to the exact event
base SHA before Bash runs the installer. It does not use `$/` for incoming scans,
because that would select candidate action contents. A modified candidate installer
cannot replace the base copy. There is no candidate fallback or manifest parser;
a missing base installer fails closed. Forks targeting Finite main receive the
same reviewed base; a separately maintained fork must first update its own base
to include the shared installer.

The main-only history job uses the native `$/` reference, which resolves the action
at the workflow's immutable running commit without a workspace checkout dependency.
The composite delegates to its own `install.sh` via `GITHUB_ACTION_PATH`; the same
script is also invoked from the exact protected incoming base. No manifest
parser or candidate local action is needed. See GitHub's
[self-repository reference](https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/).

## Reviewed Nix fixture label

The current-history audits on November 6 and 7, 2026 each reported one remaining
unclassified generic-key match. An exact recorded-ref replay of run
[42367789819](https://github.com/closure-labs/finite/actions/runs/42367789819)
identified the public Nix signing-key name `finite-nar416-fixture` at line 68 of
`scripts/bluebuild/check-native-nix-nars.py` in commit
`6afe1d9cc4d7dabd15c2cec3541a59c5e2e66758`. This is the name passed to Nix's key
generation command, not private key bytes. The fixture generates keys in a
throwaway directory and restricts its private-key file to mode 0600.

A separate exact source proof checks the immutable Git blob, full-blob SHA256,
complete line, identifier digest and parsed command structure. It contributes
only a native generic-rule AND allowance for that commit, path and whole line
when the commit is reachable. Modified lines, copied labels in new commits and
other rules remain scanned. The original 719-entry catalog and frozen baseline
are unchanged; this later commit is not required in that older snapshot. The
manifest's effective-config digest and verified-identifier count include the
additional proof when used. This does not waive credentials or certify other
history clean.
