# Validation and remediation plan

This plan implements the follow-up to PRs #139 and #140. The repository uses
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
clearance or other-profile boot compatibility. The full PR matrix can now resume
with the corrected parser; the known upstream scan-readiness blockers remain.

Local validation passed 83 focused tests, workflow/security lint, Nix formatting
and repository text/link checks. Independent QA, security and performance reviews
found no blocking source defect. No heavy local builds or scans were performed.
