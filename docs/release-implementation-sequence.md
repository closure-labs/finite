# Remediation and independent release sequence

Finite is a Jujutsu repository, using Bluefin/bootc with Nix/Home Manager. All
four desktop profiles and container tools remain supported. This is the current
execution order; older audit ledgers remain historical evidence.

## Current signing and secret-management rollout

Fresh standard [run38439778084](https://github.com/closure-labs/finite/actions/runs/38439778084)
at `b274129fc76f2bdf588b4b312d83af4759e0d1a7` passed build and security policy.
Signing received an empty secret through the reusable workflow boundary; this
is not evidence of stored-key corruption. The candidate digest is
`sha256:60b12153f6c3db4152225e6213ff5ae95971190cca87920b969a848b5fa423ef`.

1. Declare and explicitly forward only the signing secret, retain the protected
   signing environment, and check its derived public key against `cosign.pub`.
2. Validate and merge the repair. Resume that exact candidate, reusing fresh
   authenticated security evidence; do not rebuild for workflow-only changes.
3. Complete protected signing and enforcing VM install/upgrade/rollback before
   promotion. Qualify Next independently after useful standard evidence.
4. Deploy a manual Doppler canary pilot with exact OIDC trust and no production
   credentials. Verify entitlement/access and actual allow/deny results before
   moving the read-only audit App or considering signer migration.

The [Doppler assessment](doppler-oidc-assessment-2026-10-13.md) records trust
requirements and limits. Secret-store adoption is independent of image release.

PR #154 deployed the named signing boundary and Doppler pilot after source/queue
validation passed. The claims-only pilot passed; no Doppler workspace exists.
Resume38452104611 recovered the immutable candidate but stopped before signing:
sandboxed Skopeo could not read its default credential path. PR #155 provides a
private, short-lived registry auth file only around candidate inspection, preserving the non-root resource limits and all trust checks.
Corrected resume38455754348 passed native security reuse and protected signing
without rebuilding or rescanning. The key matched `cosign.pub`, and signature
and transparency verification passed. Fresh Secure Boot/encrypted-root/enforcing VM qualification passed. The upgrade
path stopped at the wrong-key rejection probe; its temporary diagnostic was
deleted, so the exact bootc error is unknown. A hosted predecessor-engine probe
observed a genuine missing-signature rejection omitted by the VM matcher. Add
that explicit rejection and preserve diagnostics, then validate the complete
upgrade/rollback path before claiming release eligibility. Current image identity
includes the VM harness, so the corrected harness requires one fresh standard
candidate; do not bypass the existing identity check to reuse its old digest.

## Historical candidate identity correction

PR #152 merged at `31cdca7ffc15b537613d0f694191fcf8e06c1f4f` after
[source](https://github.com/closure-labs/finite/actions/runs/38434206098) and
[queue](https://github.com/closure-labs/finite/actions/runs/38435138430) checks passed.
The trusted push-origin standard resume in
[38435953230](https://github.com/closure-labs/finite/actions/runs/38435953230)
stopped at the current-input identity guard before scanning or signing. The
identity enumerates generated Python bytecode, whose timestamp headers can
change between otherwise identical source checkouts.

Correct the identity calculation to exclude generated tooling caches while
retaining authored/shipped inputs. Validate deterministic identities, then build
one fresh standard candidate under the corrected identity. Old mismatched
identities are not accepted or rewritten. Standard and Next each still require
fresh exact-candidate security, protected signing and enforcing VM qualification.
Defer resume disk-cleanup optimization until the next image-workflow change;
changing that workflow now selects four extra PR builds. Do not retry the old
candidate or start Next against the same known identity failure.

## Current release continuation

PR #151 merged at `2cb7b1ed0db02aeb9a82a90bffdd511dc843c8c0`.
[Run38426200092](https://github.com/closure-labs/finite/actions/runs/38426200092)
passed all four image builds and security-policy jobs. Signing failed because
Cosign's signing-config default conflicts with the requested legacy format.
The explicit compatible flags passed a hosted ephemeral-key test, including
real transparency verification and wrong-key rejection. Exact candidates and
artifact bindings are in [the signing ledger](signing-resume-evidence-2026-10-13.json).

The initial plan was to resume standard generic first, then Next independently.
The identity failure above supersedes that attempt and requires fresh candidates. Reuse authenticated fresh native security evidence, reevaluate
current policy, and retain original timestamps. Only absent or expired evidence
permits a fresh scan; malformed evidence or policy failures stop qualification.
The resume path retains protected signing, current-main checks and enforcing VM
install/upgrade/rollback gates. No physical desktop test is required.

The historical findings below are remediation work, not automatic release holds.
Only reviewed confirmed Critical desktop exploitability can block vulnerability
acceptance under current policy; advisory/component pairs alone cannot.
Unresolved observations remain visible and are not asserted fixed or harmless.

## Verified starting point

PR #147 merged at `9d1b0c5b5ebdc7314497ee6500fba4a9c289f706`.
PR #148 head `29e8d962c063c9321ed4d4004298e4d28d77b769` passed
[all source gates](https://github.com/closure-labs/finite/actions/runs/38356992553).
The four main image builds passed in
[38353294526](https://github.com/closure-labs/finite/actions/runs/38353294526),
but its native scanner failed before policy evaluation on a relative SBOM path.
That caller bug is fixed and regression-tested in PR #148. The failed scan is
not a vulnerability verdict. Remaining identical scans were cancelled.

The latest valid retained-candidate review is
[38364577930](https://github.com/closure-labs/finite/actions/runs/38364577930):
70 standard and 119 development component/advisory pairs remain blocking under
156 scoped dispositions. These are not counts of distinct exploitable attacks.
The latest exact scope is in the
[consumer reevaluation ledger](consumer-policy-reevaluation-2026-10-13.json);
[the prior continuation ledger](desktop-applicability-continuation-2026-10-13.json)
retains inherited unknowns.
The [remaining findings](release-remaining-findings-2026-10-13.json) retain the prior
blocking pairs, affected path, risk class and scanner-reported fixed version for
standard and development profiles; a fixed-version string is not publisher proof.

## Execution order and acceptance evidence

| Order | Work and owner | Completion evidence / next action |
| --- | --- | --- |
| 1 | Finite: integrate validated scanner and applicability work | PRs #148 and #149 merged externally after passing checks; follow-up #150 retains separate security and release gates |
| 2a | Finite + owning publishers: resolve standard-channel package risks | Signed compatible owning-package fixes or complete affected-implementation proof for AnyIO, rclone, and remaining Go/network consumers; verify all live and retained paths |
| 2b | Finite: complete remaining narrow applicability leads | Exact executable/source/caller bindings; distinguish nonapplicability, backport, accepted ordinary risk and unresolved evidence; no SELinux-only clearance |
| 2c | Microsoft/Docker and Finite: development-only remediation | Bind Code dependency callers to shipped bytes; fix or prove archive/container/development findings separately; do not delay a cleared standard channel |
| 2d | Fedora + Finite: Next kernel source hold | Approved same-stream stable packages containing reviewed source fixes, authenticated module/initramfs transaction and boot evidence |
| 3 | Finite: validate one changed standard candidate | Inexpensive fixtures and signed package transaction first, then a representative image and fresh native scan by immutable digest; preserve baseline comparison and failures |
| 4 | Finite: qualify each channel that clears policy | Current digest-bound security pass, protected signing environment, encrypted Secure Boot install/upgrade/rollback, and applicable ISO/release evidence |
| 5 | Release owner: review concrete release packet | Exact digest, source/qualification revisions, successful runs, current policy, rollback target and unresolved nonblocking advisories; obtain final publication approval |
| 6 | Finite: promote only the qualified channel | Verify published digest/signature and monitor initial rollout; continue other channels independently |

Steps 2a–2d can progress independently. Start with standard generic because its
scope has fewer unresolved pairs and no Next source hold. This is a priority,
not permission to ignore development/container use or force a security pass.
If development generic clears first, it may qualify first. Next follows its own
source and boot evidence. No channel inherits another channel's clearance.

## Avoiding unnecessary runner work

- Reuse prior source/build/reference evidence where its input identity still
  matches. Do not rebuild images for qualification-tool-only PR checks.
- A cancelled workflow may contain a completed trusted build. Candidate reuse
  still requires unique successful required jobs and build steps, exact attempt,
  revision, artifact hashes, ancestry, publisher authentication and image identity.
  A cancelled or partial build itself never qualifies for reuse.
- The existing image identity includes `publication.py`. Changing that helper
  conservatively invalidates reuse of older identities even though it is tooling.
  Keep that guard; do not promise reuse of run38353294526 after this change.
  Wait for the next genuine package-remediation build rather than rebuilding only
  to refresh identity. Newly built candidates can later use the cancelled-origin
  improvement if all other reuse checks pass.
- Requery publishers after a concrete release/backport/repository event, not on a
  timer. Do not rescan an unchanged known-blocked image merely to show activity.
- Keep full SBOM processing, scans, builds and VM tests hosted. Compact reviewed
  evidence and lightweight tests may run locally. Cancel only proven redundant
  or doomed work and retain completed artifacts.

## Release decision

Source/build validation and vulnerability clearance are separate. Release is
currently ineligible. Integration, a new upstream release, ordinary-risk
acceptance or a successful scanner execution alone cannot authorize promotion.
The final release packet must pass applicable security/signing/boot gates and
identify a tested rollback target before the release owner approves publication.

## New publisher event and next concrete transaction

Fedora update [FEDORA-2026-e27d24d18c](https://bodhi.fedoraproject.org/updates/FEDORA-2026-e27d24d18c)
contains `rclone-1.75.2-1.fc44` in testing, with gating passed but stable testing
requirements not yet met at review time. Koji build3118644/RPM49086983 records
the Fedora44 signing key. The signed payload and embedded modules were subsequently
authenticated in run38361178024, as recorded below.
After approved stable promotion, validate an installed-only transaction
plus supported auth-proxy compatibility before creating a candidate. Stable
promotion does not by itself prove clearance of every embedded dependency.

The vendor RPM has no independent RPM signature, so it does not close the
previous checksum-signature trust gap. No Fedora44 AnyIO4.14.2 build or published
update was observed; a signed owning update or verified backport remains needed.
Exact official requests, responses, source/build identifiers and limitations are
retained in [package options](release-package-options-2026-10-13.json). No testing
repository was enabled, no package installed, and no risk exception added.

The [bounded next-applicability review](release-next-applicability-2026-10-13.json)
proves no additional release-affecting exemption. The Skopeo SSH lead is already
nonblocking. Next internal proof work must bind actual gRPC server/auth
interceptors and HTTP2/CONNECT handlers to authenticated source and shipped build
tags. Compiled-package lists alone cannot establish caller reachability, and
client use does not rule out hostname, proxy, CONNECT or module-fetching attacks.
Keep those unresolved findings visible; do not spend another old-candidate scan
on a zero-blocker classification change.

## Authenticated candidate and actual HTTP callers

[Read-only rclone reference inspection](https://github.com/closure-labs/finite/actions/runs/38361178024)
passed before stable promotion. The [signed reference](rclone-signed-reference-2026-10-13.json)
contains Go1.26.9, x/crypto0.57.0 and x/net0.60.0.
[Advisory-by-advisory review](rclone-prospective-remediation-2026-10-13.json)
supports prospective fixes for all14 currently recorded rclone-owned pairs in
the reviewed standard/development candidates. The gRPC development-version
comparison uses specific source-fix evidence, not version ordering alone.
This does not clear the old installed binaries or a future image automatically.

Fedora's package spec skips relevant S3/FTP/SFTP tests. Before adopting the
package, Finite still needs its supported auth-proxy, session-isolation, copy,
mount and protocol compatibility tests, as well as stable-source, transaction
and exact-candidate gates. No testing source is enabled by this inspection.

[HTTP caller review](http-caller-review-2026-10-13.json) verifies23 immutable
source files. Podman's optional TLS API has an actual server path. Profiling
and interactive-signing handlers also prevent blanket client-only treatment.
Exact advisory prerequisites and proxy/exposure consequences remain distinct;
no unobserved scanner record was fabricated and no new disposition was added.

PR148 merged externally at4bab5195db5d92d59c28907dba102dc01e076a32 after
merge-queue run38360619132 passed. Its automatic main reconciliation then
launched four builds despite only qualification/evidence changes. Run38361032151
was cancelled as redundant while existing package blockers remained. Keep
manual changed-candidate work behind the prerequisites above; published-channel
reconciliation can still select stale channels and is not a clearance signal.

The [authenticated source census](grpc-source-census-2026-10-13.json) passed
run38362940891 and eleven hosted parser fixtures after the first census
38362022050 identified specific constructor/initializer/linkname gaps. It parsed
13,286 Go files from
three exact publisher archives; only the two ocicrypt key-provider packages are
non-gRPC compiled-package candidates importing gRPC in these applications.
Complete selected package source is retained for independent caller review.
The census alone is not call-graph proof and grants no disposition.


## Reviewed consumer scopes and compatibility continuation

The [complete gRPC caller review](grpc-caller-review-2026-10-13.json) and
[independent scope verification](grpc-independent-review-2026-10-13.json)
approve six exact historical-digest dispositions for the server-authorization
advisory GHSA-p77j-4mvh-x3m3. Each covers only the four verified Podman/Buildah
live and retained paths. The policy now has 156 scoped dispositions;69 focused
fixtures pass. Podman-tui remains unproven, and the shared transport advisory
GHSA-hrxh-6v49-42gf remains blocked because the actual client queues peer-controlled
window updates without the fixed accounting. New main digests require new joins.
[Hosted retained-evidence reevaluation](consumer-policy-reevaluation-2026-10-13.json)
passed in run38364577930: standard blocking pairs declined71→70; development
remains119 because podman-tui is unproven. All six original results reproduced
and scanner observations remained unchanged. These counts are policy outcomes,
not a claim that every remaining finding is exploitable.

PR149 merged externally at1240490583072257def95727f199df41e59fe053 after
queue38362921128 passed. The redundant automatic main image run38363454043 was
cancelled: its changes only concern reference tooling and evidence. Follow-up
implementation uses the separate JJ bookmark security/consumer-compatibility.

The [compatibility plan](rclone-compatibility-plan-2026-10-13.json) defines positive
and negative controls. The new hosted-only harness implements ordinary operations,
link containment, FTP session authority and two Restic traversal contracts.
Its19 offline tests and independent QA pass. [Actual hosted compatibility](rclone-compatibility-evidence-2026-10-13.json)
passed all five implemented contracts in run38366200031 atcf349b5a62f577de31fc04d0f65bb8a709539d4d.
The first two attempts exposed fixture issues (invalid passive range and a narrow
FTP response-code expectation), not candidate vulnerabilities; both are retained.
SFTP/Windows, RC per-server proxies, S3 identity secrets and mounting remain
explicit coverage gaps owned by Finite. Implement their planned positive/negative
fixtures before claiming complete compatibility; then require approved stable
promotion and a signed installed-only transaction before candidate image work.
Partial success cannot grant package adoption, vulnerability clearance or release eligibility.


Final implementation head1b4d0cf2be9e217523ab9e29bb4e30e7ec0631fb passed all
[hosted source gates](https://github.com/closure-labs/finite/actions/runs/38366217513).
Source/build-contract verdict: PASS. Vulnerability-clearance verdict: BLOCKED.
Release-eligibility verdict: INELIGIBLE. The temporary validation branch was
deleted after retaining artifacts; no image rebuild, merge or release publication
was performed by this continuation.


## VM-sufficient desktop qualification continuation

The release owner explicitly selected VM qualification as sufficient; a separate
physical-hardware or manual graphical-desktop gate is not required. The new
[qualification contract](desktop-release-qualification.md) retains untested
physical/GUI coverage as informational and preserves security, signing, encrypted
Secure Boot install, upgrade and rollback requirements.

The [official prerequisite refresh](release-prerequisites-refresh-2026-10-13.json)
found rclone1.75.2 still testing-only and no fixed AnyIO4.14.2 Fedora44 build.
Next7.2.9-301 now meets testing requirements and has a stable request/pending tag,
but approved stable promotion was not observed. No package floor/source changes
are justified yet; a stable request is not an approved repository transaction.

RC per-server proxy and S3 identity-secret compatibility contracts have been
implemented, with30 offline fixtures passing and independent review approval.
[Actual hosted validation](rclone-protocol-compatibility-2026-10-13.json)
passed all seven implemented cases in run38368702487. Shared-backend S3 multipart/metadata,
SFTP/Windows and mounting remain explicit package-compatibility gaps; these are
distinct from the rejected physical-workstation qualification requirement.

The [implementation validation ledger](desktop-qualification-validation-2026-10-13.json)
records612 passing offline tests and the source-CI fixture correction. PR151
tracks exact-head hosted checks. Actual new VM execution remains pending a useful
changed candidate; source fixtures do not count as an end-to-end boot pass.

## Critical-only desktop release threshold

The release owner narrowed vulnerability blocking to Critical findings applicable
to desktop use with SELinux enforcing. Lower severities remain tracked even when
previously categorized serious or known exploited. This is explicit risk acceptance,
not evidence that those vulnerabilities were repaired. Unknown Critical applicability
stays pending review; exact nonapplicability/backport proof and all authenticity,
security-evidence validity and VM boot gates remain required.

[Hosted reevaluation](critical-desktop-policy-evidence-2026-10-13.json) reused
all four fresh native scans from run38395796884 without rebuilding or rescanning.
The original policy results reproduce and observations remain unchanged.
Standard Generic/Next each move93→24 blocking component/advisory pairs;
development Generic/Next each move146→54. Different package versions can share
one advisory; these counts are not distinct exploits. Current candidate digests
are recorded in the ledger. Historical digest-scoped dispositions do not silently
transfer to these newer digests.

Generic evaluations completed in38411151441 before a Next baseline filename
error stopped that diagnostic. Run38411349067 completed only the missing Next
comparisons. The first38410999928 failure exposed legacy output-shape drift;
that compatibility defect was corrected and regression tested. These probe failures
are distinct from the resulting Critical applicability blockers.

PR150 merged externally at5c7480cb87e32379834bd6f34b23c07ce1644d73;
PR151 is rebased on main. The redundant four-image post-merge run38410619261
was cancelled after verifying only policy/evidence/validation inputs changed and
the latest same-payload native evidence already existed. No release was performed.

Next work is exact consumer applicability and safe optional-package removal
validation for the remaining Critical findings. Pending noncritical fixes and
optional-upgrade compatibility work no longer categorically hold release.

## Advisory pairs are not release blockers

The owner clarified that scanner/advisory pairs alone cannot justify blocking
release. The explicit `reviewed-desktop-exploitability` basis supersedes the
prior pair-based verdicts above. Critical matches with unresolved applicability
are retained as nonblocking review work, not declared fixed or harmless.

Only a reviewed Critical record with the exact image/profile/component/files,
affected-code evidence, supported attacker path/preconditions, impact and
SELinux assessment can block vulnerability acceptance. Confirmed records work
even without a scanner match. Complete source/caller/configuration evidence is
admissible; executing an exploit is not mandatory.

Independent review found no existing receipt satisfying that full confirmation
standard for the four current candidates. The current confirmed registry is
therefore explicitly empty. Signing, freshness/integrity of security evidence,
SELinux-enforcing VM installation/upgrade/rollback and release approval remain
required. Do not delay those gates solely for unresolved advisory counts.

[Hosted verification38414548421](reviewed-desktop-policy-evidence-2026-10-13.json)
passes the revised vulnerability policy for all four immutable candidates with
zero confirmed blockers. All original native observations remain unchanged.
Standard24/development54 Critical pairs remain unresolved advisories, not release
holds. No new scan, image build or package mutation was performed. The next
release work is trusted-main signing and exact-candidate VM qualification, with
standard Generic first; it is no longer gated on advisory-count reduction.
