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

The last valid retained-candidate review is
[38356296590](https://github.com/closure-labs/finite/actions/runs/38356296590):
71 standard and 119 development component/advisory pairs remain blocking under
150 scoped dispositions. These are not counts of distinct exploitable attacks.
The current exact scope and unknowns are in the
[continuation ledger](desktop-applicability-continuation-2026-10-13.json).
The [remaining findings](release-remaining-findings-2026-10-13.json) retain every
blocking pair, affected path, risk class and scanner-reported fixed version for
standard and development profiles; a fixed-version string is not publisher proof.

## Execution order and acceptance evidence

| Order | Work and owner | Completion evidence / next action |
| --- | --- | --- |
| 1 | Finite: integrate validated scanner and applicability work | PR #148 source/QA/security review passes at its final head; integration does not establish release eligibility |
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
the Fedora44 signing key; payload signature verification is still pending.
After approved stable promotion, authenticate the full RPM on a hosted runner,
inspect embedded Go/module versions, and validate an installed-only transaction
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
