# Validation and remediation plan

The current all-profile desktop applicability work is tracked in
[the desktop continuation plan](desktop-security-validation-plan.md). Its threat
scope and later queue events update the historical continuation below; prior
passed evidence remains valid and vulnerability/release gates remain separate.

This document retains the completed follow-up to PRs #139 and #140. Both have
merged; PR #140 merged at `1bf562527742`, and documentation PR #143 merged at
`be90c0a83126`. Current work uses the isolated Jujutsu desktop-security workspace.
The user authorized further remediation, optional generic virtual-camera removal,
and now removal of host ZFS support from all four profiles. Release eligibility still requires the security and boot gates. Current
evidence and pending validation are recorded in
[the desktop ledger](desktop-security-evidence-2026-10-12.json).

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

## Historical executed results and blockers

Two benchmark pairs passed with lower cold and warm setup time and a smaller
closure. The second run also verified artifact retention; no further benchmark
repeat is needed. See [paired measurements](ci-tool-benchmark-2026-10-12.json).

[Hosted prerequisites run 38294546850](https://github.com/closure-labs/finite/actions/runs/38294546850)
verified availability of all 16 current RPM floors. It reused the authenticated
native SBOM without extracting or scanning the baseline image again. Every one
of the 281 component PURLs matched; 244 have identified RPM owners and 37 remain
without identified ownership. [The compact evidence](remediation-prerequisite-evidence-2026-10-12.json)
retains source artifact hashes and package versions.

Three owning-package fixes were unavailable in the retained approved Fedora
probe. Refresh lightweight metadata before treating that historical state as a
current package-availability conclusion:

| Owning package | Available upstream version | Advisory fixed version |
| --- | --- | --- |
| python3-anyio | 4.13.0 | 4.14.2 |
| python3-msgpack | 1.1.2 | 1.2.1 |
| rclone | 1.74.3 | 1.75.1 |

Queried Go-owning RPMs also already match Fedora's newest versions. Tailscale
uses a separate source and the scanned cosign binary has no RPM owner. Later
source review established that Finite's BlueBuild generator inserts Cosign; the
current desktop continuation pins the authenticated official 3.1.3 OCI source.
Its actual Go 1.26.4 and modules remain below some security fix boundaries. The
generic kernel update now has successful package transactions, with final
pruning/initramfs, assembled-image and boot validation still pending.

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

## Historical continued remediation

[The refreshed hosted probe](https://github.com/closure-labs/finite/actions/runs/38299553401)
completed on 2026-10-12 at 19:44 UTC. At that observation all 16 floors were
available; AnyIO, msgpack and rclone were below the reviewed fixed versions. Exit 1 is the
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
| cosign | Sigstore / BlueBuild; Finite verifies copied executable | 3.1.3 OCI update fixes legacy bundles; actual Go 1.26.4, x/crypto 0.53.0 and x/net 0.56.0 still need publisher fixes and fresh image evidence |
| Generic kernel | Finite validation of approved Fedora 44 source | 7.2.9-201 signed transactions passed after authorized optional-camera removal; confirm latest pruning guard, initramfs/image contracts and boot qualification |
| Next kernel | Fedora 45 publisher / pending user decision | 301 testing build has passed gating and requested stable; obtain stable publication or an explicitly reviewed exception before updating |
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

- Source/build: original and PR #140 four-profile matrices passed. Those results
  do not cover the latest desktop/kernel source; its focused probes passed, while
  patched-copy scanning and final all-profile integration remain pending.
- Vulnerability clearance: blocked. The refreshed prerequisite report and signed
  package module evidence are not a fresh native image scan. No baseline finding
  is marked resolved.
- Release eligibility: blocked. Fresh digest-bound native scan evidence, signing
  gates and affected-profile boot qualification remain mandatory before promotion.

The historical readiness gate avoided repeated scans of an unchanged blocked
image. The current desktop continuation authorizes one representative patched,
unpublished OCI copy to measure the verified fixes, while known blockers remain.
Compare every baseline finding, retain new findings and unknowns, then broaden
qualification only when useful. No additional merge, image publication or
signing-key retirement is part of the current continuation.

[Combined transaction run 38300150513](https://github.com/closure-labs/finite/actions/runs/38300150513)
passed on the authenticated pinned generic base: the existing Fedora floors and
new signed vendor update satisfied their assertions, protected boot packages
remained unchanged, and both second invocations skipped repository/vendor access.
This does not imply that networking was physically disconnected. Source hashes
and retained log hashes are in the continuation evidence. The historical final
four-profile matrix passed at `a83a210baf2d` in
[run 38300840732](https://github.com/closure-labs/finite/actions/runs/38300840732).
The latest desktop changes require their own final integration evidence.

All 100 focused tests passed, including 17 vendor authentication/transaction tests.
Actionlint, Zizmor, Nix formatting and text/link checks passed. Independent security,
QA, performance and readability review found no blocking source defect. No local
Nix evaluation, image build/scan, package mutation or VM build ran.

## Current desktop continuation

The user-approved generic virtual-camera removal permits the authenticated
Fedora 44 7.2.9-201 update; standard and DX transactions passed in
[run 38311107555](https://github.com/closure-labs/finite/actions/runs/38311107555)
at `5b961c8d`, including offline repeats. The newer module-tree pruning guard has
25 passing fixtures and awaits hosted confirmation. Both generic recipes now
regenerate initramfs after replacement/profile metadata and before finalization;
four recipe-contract and four initramfs fixtures pass. Container RPM installation
alone does not generate the boot payload.

[Go evidence run 38310504908](https://github.com/closure-labs/finite/actions/runs/38310504908)
completed metadata/platform inspection of 22 selected live paths at
`e1d7a1e5a13e17995d6da0bdc0708bca5f8ccbee`. Module, symbol and compiler-suffix
stdlib coverage limits remain explicit. Cosign 3.1.3 is a verified partial
legacy-bundle fix, with actual vendor bytes still carrying unfixed Go/modules.
The publication-order fix has ten passing fixtures. The stable-tag updater has
twelve fixtures and never queries testing/pending/candidate tags. Next 301
remains a pending testing-update decision; no exception has been implemented.

The unpublished local-candidate scanner has 17 fixtures and reuses production
scan policy. Production verification rejects explicit diagnostic markers before
release processing; 27 policy tests cover this boundary. Its first hosted scan,
final PR/source integration, and affected-profile boot qualification are pending.
See [the desktop plan](desktop-security-validation-plan.md) and
[current evidence](desktop-security-evidence-2026-10-12.json). Source/build,
vulnerability clearance and release eligibility remain separate; no baseline
finding is resolved automatically.

## Authorized host ZFS removal

The user has now authorized removing host ZFS across all four Finite profiles.
The historical failure in
[run 38314613864](https://github.com/closure-labs/finite/actions/runs/38314613864)
and [ownership probe 38315879860](https://github.com/closure-labs/finite/actions/runs/38315879860)
remain evidence that the prior guard correctly refused retained owned modules.
They do not establish success of the new explicit package-removal implementation.
Remove only reviewed ZFS package names and preserve unrelated-package inventory,
authentication and stale-tree ownership checks. Matching publisher ZFS modules
are no longer a product prerequisite; host ZFS is no longer supported.

[Source contracts 38317182847](https://github.com/closure-labs/finite/actions/runs/38317182847)
passed historical source `4bc79ded4fcf4cfe0d426f9d0bca2f03800b34db`.
[Draft PR #144](https://github.com/closure-labs/finite/pull/144), last posted head
starting `9a65`, now has changing runtime source. New focused/source/Nix checks,
all four image builds, one useful patched-copy native scan and eventual boot
qualification are pending. The fresh prerequisite portion of run 38314613864
still found approved AnyIO/msgpack/rclone fixes unavailable; other Go findings
remain unresolved. Baseline statuses remain unchanged.

Next 301 is a separate unapproved testing choice; retain 300 and the strict
stable-tag policy while its October XFS/AMD security gap remains explicit.
The user's proposed FreeBSD VM storage alternative is outside validated
installation guidance and cannot be claimed to replace the host root filesystem.
Vulnerability clearance and release eligibility remain blocked; historical source
checks are not new-source or native/boot clearance.

## Authenticated consumer continuation — 2026-10-13

PR #147 merged externally at `9d1b0c5b5ebd`; PR #148 now targets main.
The user approved independent channel qualification: generic channels can proceed
as their own security, signing and boot gates clear, while Next retains its hold.

Implemented 27 cmd/go runtime mismatch scopes and 72 independently reviewed
consumer/sumdb scopes, bringing the exact-digest policy to 150 dispositions.
Signed RPM payloads, verified source archives and owning compilation records
prove the named consumer mismatches; these are nonapplicability determinations,
not package fixes or blanket dependency suppressions. New main digests need new
bindings. All 107 focused policy/evidence/selection tests passed.

[Hosted source proof](https://github.com/closure-labs/finite/actions/runs/38354387254)
passed. [Retained policy reevaluation](https://github.com/closure-labs/finite/actions/runs/38356296590)
passed: unchanged observations now yield 71 standard and 119 development
blocking pairs, down from 87 and 135 under the previous reviewed policy.
Owners, unblock evidence and separate verdicts are retained in
[the continuation ledger](desktop-applicability-continuation-2026-10-13.json).
Compiler/cgo, unresolved network consumers, AnyIO, rclone and the Next source
hold remain explicit. Release eligibility has not been established.
