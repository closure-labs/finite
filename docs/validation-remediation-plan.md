# Validation and remediation plan

This plan implements the follow-up to PRs #139 and #140. PR #139 has merged;
PR #140 now targets main. The repository uses
Jujutsu; work stays in the isolated `security-remediation` workspace. User
requests authorize this plan and its implementation. Release eligibility still
requires the security and boot gates to pass.

## Sequence and acceptance criteria

| Step | Work | Acceptance criterion |
| --- | --- | --- |
| 1 | Finish existing PR #139 validation | Four image profiles plus Nix/runtime and documentation checks pass |
| 2 | Measure old and proposed Nix tool setup on separate hosted runners | Record cold/warm elapsed time and closure sizes; retain the change only with no observed setup regression |
| 3 | Probe Fedora 44 repositories before further image work | Record available NEVRA for every RPM floor and candidate owning package; unavailable fixes remain explicit blockers |
| 4 | Extend targeted remediation using verified ownership and versions | Native RPM ordering, signed Fedora repos, protected boot stack, no pip overlays, broad upgrades, or blanket ignores |
| 5 | Validate one representative image and scan its immutable digest | Real DNF transaction succeeds, image assertions pass, fresh native scan produces an honest ledger delta |
| 6 | Validate remaining profiles and kernel changes separately | All affected profiles build; kernel changes require authenticated matching-release packages and boot qualification |
| 7 | Review release eligibility | Full scan policy, isolated signing and VM qualification pass before promotion |

Steps 2 and 3 may run concurrently with already-useful validation. Do not launch
another full matrix merely to probe package availability. Cancel only proven
failed, superseded, or redundant runs; preserve useful in-progress checks.

## Remaining remediation scope

The baseline ledger contains 58 RPM pairs, 213 embedded Go pairs, eight generic
kernel pairs and two Python pairs. The Python findings include AnyIO and msgpack.
Their advisory fixed versions are 4.14.2 and 1.2.1 respectively. Establish RPM
ownership and available Fedora builds before adding floors; never use pip to
replace files managed by the system RPM database.

For Go findings, update the owning executable package, then check the embedded
module inventory in a fresh scan. An installed compiler update is insufficient.
For the generic kernel, retain Fedora 44 ownership and authentication. The next
profile's separately pinned Fedora 45 kernel is not an automatic substitute.
Old-version/backport matches and duplicate OSTree objects require evidence-based
triage; they do not justify changing the global severity policy.

## Resource and trust limits

All Nix evaluations/builds, full SBOM parsing, image scans, package repository
probes and VM tests run on GitHub. Local checks are bounded fixture tests and
small metadata reads. Temporary validation branches request read-only repository
access, no audit App credentials and no signing environments. Delete temporary
remote refs when their evidence is retained; preserve run artifacts.

No fresh scan of the unchanged known-blocked baseline is useful. A successful
source test or package probe does not close a vulnerability. Only new image
evidence can mark baseline ledger entries resolved.

## Initial evidence

- PR #139: all four image profiles passed in
  [run 38291339249](https://github.com/closure-labs/finite/actions/runs/38291339249).
- PR #140: [run 38293809846](https://github.com/closure-labs/finite/actions/runs/38293809846)
  started; its existing work is retained while useful.
- Pre-merge benchmark launched using an isolated branch and a registered workflow
  path in [run 38294108271](https://github.com/closure-labs/finite/actions/runs/38294108271).
  This avoids changing the main audit workflow or requiring a premature merge.

Results and concrete blockers are recorded below as each stage completes.

## Executed results and current blockers

Two benchmark pairs passed with lower cold and warm setup time and a smaller
closure. The second run also verified artifact retention; no further benchmark
repeat is needed. See [paired measurements](ci-tool-benchmark-2026-10-12.json).

[Hosted prerequisites run 38294546850](https://github.com/closure-labs/finite/actions/runs/38294546850)
verified availability of all 16 current RPM floors. It reused the authenticated
native SBOM without extracting or scanning the baseline image again. Every one
of the 281 component PURLs matched; 244 have identified RPM owners and 37 remain
without identified ownership. [The compact evidence](remediation-prerequisite-evidence-2026-10-12.json)
retains source artifact hashes and package versions.

Three known owning-package fixes are unavailable in the approved Fedora repos:

| Owning package | Available upstream version | Advisory fixed version |
| --- | --- | --- |
| python3-anyio | 4.13.0 | 4.14.2 |
| python3-msgpack | 1.1.2 | 1.2.1 |
| rclone | 1.74.3 | 1.75.1 |

Queried Go-owning RPMs also already match Fedora's newest versions. Tailscale
uses a separate source and the scanned cosign binary has no identified RPM
owner. Those cases require publisher/source-specific remediation, not a blind
Fedora upgrade. The generic kernel remains a separate authenticated update and
boot-validation task.

The prerequisite probe now distinguishes availability of the 16 implemented
floors from readiness for another full scan. An unavailable known owning-package
fix blocks scan readiness, with exit status 1 and retained evidence; malformed
or failed probes use status `error`. This triage control does not weaken the
production scan policy. Even a ready prerequisite result is not scan clearance.

Keep current image builds that can prove the targeted transaction. Defer another
full candidate scan until prerequisite versions change or a reviewed alternative
fix exists. At that point compare the fresh digest-bound result with the baseline
using `scripts/ci/security-remediation-diff.py`; `notObserved` is a comparison
result, never automatic proof that a vulnerability was fixed. No source-built
replacement package, pip overlay, or broad exclusion was introduced to force a
passing result.

## Transaction validation

The first PR140 image attempt exposed an inventory parser bug: legitimate
`gpg-pubkey` records report architecture `(none)`. The remaining jobs sharing that
failure were cancelled. The parser now accepts only that exact pseudo-package
case, retains its record, and rejects other malformed architecture/version fields
with a bounded diagnostic. Native RPM and fixture regression tests cover it.

[Focused transaction run 38295423922](https://github.com/closure-labs/finite/actions/runs/38295423922)
passed on the authenticated pinned generic Bluefin base. It applied the actual
bounded DNF transaction, verified the floors and protected boot stack, then ran
the helper again and verified its already-satisfied/no-repository-access path.
This establishes base transaction behavior, not final-image vulnerability
clearance or other-profile boot compatibility. The corrected full matrix passed all four image builds and runtime inspections,
documentation, Nix contracts and CI gate in
[run 38295992049](https://github.com/closure-labs/finite/actions/runs/38295992049),
at `f506ae341663`. The known upstream scan-readiness blockers remain.

Local validation passed 83 focused tests, workflow/security lint, Nix formatting
and repository text/link checks. Independent QA, security and performance reviews
found no blocking source defect. No heavy local builds or scans were performed.

## Continued remediation

[The refreshed hosted probe](https://github.com/closure-labs/finite/actions/runs/38299553401)
completed on 2026-10-12 at 19:44 UTC. All 16 floors remain available; AnyIO,
msgpack and rclone remain below the reviewed fixed versions. Exit 1 is the
expected `blocked` readiness result, with the native inventory parser passing.
The original ownership inventory is reused, avoiding another full SBOM parse.
[Retained continuation evidence](security-continuation-evidence-2026-10-12.json)
binds the small reports to their source hashes and workflow revisions.

A newer signed vendor package makes a partial Tailscale update actionable.
[Hosted RPM inspection](https://github.com/closure-labs/finite/actions/runs/38299748350)
verified Tailscale `0:1.104.1-1` against the exact reviewed payload/key hashes and
public-key fingerprint, then inspected both actual executable module manifests.
The shipped binaries contain Go 1.27.1, x/crypto 0.57.0, x/net 0.59.0 and x/text
0.42.0; the CLI also contains x/image 0.46.0. These advance several baseline
modules, while newer Go 1.27.2 and x/net 0.60.0 fixes remain unmet. The 23 baseline
pairs involving the owning Tailscale package remain pending rescan; shared module
findings also occur in other owning executables.

The separate installed-only helper authenticates the locked stable vendor RPM
using an isolated RPM key database before import or DNF. It enforces local RPM
signature checking, Fedora-only dependencies, native version ordering, unchanged
protected boot packages and installed architecture. It skips vendor access when
absent or already at the floor. The existing Fedora remediation remains restricted
to Fedora packages. A necessary vendor transaction adds download/transaction work
when outdated; it is not an additional runner optimization claim.

### Residual owners and unblock events

| Scope | Responsible publisher / Finite action | Evidence needed to unblock |
| --- | --- | --- |
| AnyIO / msgpack | Fedora package maintainers; Finite reviews new builds | Approved Fedora 44 builds at 4.14.2 / 1.2.1, or exact documented backport proof |
| rclone | Fedora rclone maintainer | Approved build at 1.75.1, followed by embedded-module reassessment |
| Other Go binaries | Owning Fedora or vendor package maintainers | Rebuilt owning executables with the required embedded Go/module fixes; compiler upgrades alone do not qualify |
| Tailscale | Tailscale stable publisher | Signed stable RPM with Go 1.27.2 and x/net 0.60.0 fixes, followed by native image evidence |
| cosign | Sigstore / Bluefin; Finite verifies historical provenance | Hash/version/build metadata and exact source of baseline `/usr/bin/cosign`, then an authenticated compatible replacement containing required fixes |
| Generic kernel | Fedora 44 / Bluefin publishers | Authenticated same-release kernel containing the relevant fixes through 7.2.8, plus boot qualification |
| Ownership gaps / OSTree objects | Finite security review | Exact package/path or source evidence and reachability proof, without assumed ownership from relationships |

[Official AnyIO advisory](https://github.com/advisories/GHSA-82r6-8w77-94w6),
[msgpack advisory](https://github.com/advisories/GHSA-6v7p-g79w-8964), and
[rclone advisories](https://github.com/advisories/GHSA-p569-5gjg-9cmj)
[confirm the reviewed version boundaries](https://github.com/advisories/GHSA-xwwr-4h3p-r22c).
The latest reviewed
[cosign release source](https://github.com/sigstore/cosign/blob/v3.1.3/go.mod)
also precedes some required embedded-module versions; replacing a binary merely
because it is latest does not establish clearance.

Two narrowly scoped applicability leads remain open for exact evidence review:
[GO-2026-6604](https://vuln.go.dev/ID/GO-2026-6604.json) declares Windows imports;
[CVE-2020-27815](https://cveawg.mitre.org/api/cve/CVE-2020-27815) has an old
[JFS fix](https://github.com/torvalds/linux/commit/c61b3e4839007668360ed8b87d7da96d2e59fc6c).
The exact scanned Linux/kernel artifacts must be shown unaffected before any
exception review. No exception or automatic resolution is applied.

### Separate validation verdicts

- Source/build: original four-profile matrix passed; the continuation adds focused
  authentication/transaction tests. Current integration results are recorded on
  [PR #140](https://github.com/closure-labs/finite/pull/140) for its exact new head.
- Vulnerability clearance: blocked. The refreshed prerequisite report and signed
  package module evidence are not a fresh native image scan. No baseline finding
  is marked resolved.
- Release eligibility: blocked. Fresh digest-bound native scan evidence, signing
  gates and affected-profile boot qualification remain mandatory before promotion.

Keep the full candidate scan deferred while the explicit readiness gate is blocked,
unless a reviewed alternate fix changes that decision. Run one changed candidate
first when that gate becomes ready; compare every baseline finding, retain new
findings and unknowns, then broaden qualification as necessary. No merge, image
publication, or signing-key retirement is part of this continuation.

[Combined transaction run 38300150513](https://github.com/closure-labs/finite/actions/runs/38300150513)
passed on the authenticated pinned generic base: the existing Fedora floors and
new signed vendor update satisfied their assertions, protected boot packages
remained unchanged, and both second invocations skipped repository/vendor access.
This does not imply that networking was physically disconnected. Source hashes
and retained log hashes are in the continuation evidence. One final four-profile
integration matrix validates the recipe changes; its exact head and terminal
results are recorded on PR #140 to avoid another build merely to commit CI links.

All 100 focused tests passed, including 17 vendor authentication/transaction tests.
Actionlint, Zizmor, Nix formatting and text/link checks passed. Independent security,
QA, performance and readability review found no blocking source defect. No local
Nix evaluation, image build/scan, package mutation or VM build ran.
