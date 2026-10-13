# Remediation and independent release sequence

Finite is a Jujutsu repository, using Bluefin/bootc with Nix/Home Manager. All
four desktop profiles and container tools remain supported. This is the current
execution order; older audit ledgers remain historical evidence.

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
