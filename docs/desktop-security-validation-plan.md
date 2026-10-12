# Desktop security validation

This continuation covers all four Finite profiles, their desktop applications,
development tools and container runtimes. Finite uses Bluefin/bootc with Nix/Home
Manager. Changes use Jujutsu in the isolated desktop-security workspace. The
user authorized implementation, optional generic virtual-camera removal, and
now removal of host ZFS support from all four profiles. The separate next-kernel
testing exception remains unapproved.

Prior evidence is retained. [PR #140](https://github.com/closure-labs/finite/pull/140)
passed all four builds, runtime inspections, Nix contracts, documentation and the
CI gate at `a83a210baf2d` in
[run 38300840732](https://github.com/closure-labs/finite/actions/runs/38300840732),
then merged at `1bf562527742`. Its 100 focused tests and two tool-setup benchmarks
do not need repeating. [PR #143](https://github.com/closure-labs/finite/pull/143)
passed documentation/CI checks in
[run 38305327730](https://github.com/closure-labs/finite/actions/runs/38305327730)
and merged at `be90c0a83126`. Those merges were separately requested. This
continuation does not authorize another merge or publication.

## Desktop threat model

Prioritize host takeover, privilege escalation, authentication/TLS failures,
archive/path escape, dangerous parsing of malicious websites/downloads/files,
and data theft or corruption. Assess container build/run/import workflows,
rootless and privileged boundaries, exposed VPN/remote-desktop services, and
development tools that consume attacker-controlled repositories or artifacts.
Process-local crashes still require exact consumer, input and privilege review.

SELinux enforcing is a required control; it does not establish confinement of
every desktop process. Workstation observations show Firefox/GNOME in
`unconfined_t`, Tailscale in `unconfined_service_t`, and SSH in `sshd_t` while
enforcing. These observations do not qualify a candidate image. The candidate VM
must record actual enforcement, process domains, listeners and supported
container behavior. [Fedora documents the unconfined policy](https://fedoraproject.org/wiki/SELinux/Policies).
Do not treat SELinux, an advisory's server wording, or missing symbols as a
blanket mitigation or waiver. Retain all findings, KEV blockers and unknowns.

## Completed evidence and remediation

[The compact evidence ledger](desktop-security-evidence-2026-10-12.json) binds the
following observations to run revisions, immutable sources and artifact hashes.
Baseline finding statuses remain unchanged.

- [Go evidence run 38310504908](https://github.com/closure-labs/finite/actions/runs/38310504908),
  at `e1d7a1e5a13e17995d6da0bdc0708bca5f8ccbee`, completed diagnostic inspection
  of all 22 selected live executable paths in the authenticated baseline image.
  Every path has hash and Linux/amd64 metadata. Some symbol/module coverage and
  compiler-suffix stdlib coverage remain explicitly unknown. The collector reads
  executable bytes without running image code; historical OSTree objects remain
  outside its selected-live-path scope.
- The official govulncheck v1.9.0 protocol is retained. JSON exit zero is not
  clearance, repeated traces are not distinct vulnerabilities, and binary mode
  has no call graph. Silent module fallback and incomplete inline-symbol coverage
  remain limits. [Official usage](https://pkg.go.dev/golang.org/x/vuln/cmd/govulncheck)
  and [the pinned protocol](https://github.com/golang/vuln/blob/v1.9.0/internal/govulncheck/govulncheck.go)
  explain these boundaries.
- Finite's pinned BlueBuild generator inserts Cosign into `/usr/bin`; the
  baseline executable is v3.1.1 with Go 1.26.3. All four recipes now pin the
  authenticated official v3.1.3 OCI index. Actual vendor executable inspection
  records SHA256 `a57926e24b07f02b5baf3be81f9a5988e9e45d8a1ca8ca500cdf56d10e69f887`,
  Go 1.26.4, x/crypto 0.53.0 and x/net 0.56.0. This is a partial
  [legacy-bundle verification fix](https://github.com/sigstore/cosign/security/advisories/GHSA-fx35-mq7g-6g98),
  not embedded-Go vulnerability clearance. Source/go.mod or release-asset versions
  cannot substitute for this OCI executable evidence.
- The user approved removing generic `kmod-v4l2loopback` and `v4l2loopback`.
  The generic helper authenticates the exact Fedora 44 `7.2.9-201.fc44` package
  set, preserves unrelated packages and matching development dependencies, and
  verifies the replacement before retiring recorded old kernels. Standard and DX
  base transactions passed in
  [run 38311107555](https://github.com/closure-labs/finite/actions/runs/38311107555)
  at `5b961c8d`, including offline repeat runs. A newer guard refuses to delete
  owned, unexpected or symlinked stale module files; 25 focused fixtures pass,
  and the historical hosted attempt correctly rejected a retained ZFS owner.
  The user has since approved removing host ZFS; that changed implementation
  needs fresh validation rather than reusing the earlier package-run success. Both generic recipes now
  regenerate initramfs after replacement and profile metadata, before finalization:
  RPM installation in a container does not create the required boot payload.
  See [the generic kernel plan](generic-kernel-remediation-plan.md).
- Publication preparation now authenticates all four canonical recipe identities
  before rewriting candidate tags. Ten workflow-order regression tests cover
  both modes, wrong tags and failed authentication. This corrects the pre-build
  failure in [run 38306934392](https://github.com/closure-labs/finite/actions/runs/38306934392);
  that failed run produced no candidate digest or fresh scan.
- The next-kernel updater checks only exact `f45` and `f45-updates` tags. Twelve
  fixtures cover stable promotion, empty stable tags, numeric version ordering,
  malformed/oversized responses and rejected testing/pending/candidate tags.
  Existing signature, downgrade, module and seven-day freshness guards remain.

## Next kernel and residual blockers

The pinned Fedora 45 next kernel `7.2.9-300.fc45` lacks the later October XFS/AMD
fixes. The signed `7.2.9-301.fc45` update is still in testing: gating passed,
stable promotion requested, karma 9 and no stable date in the retained response.
Gating success and a stable request do not establish stable publication.
The user's testing-update preference remains pending; no override is implemented.
The `7.2.10` pending/gating-failed candidate is excluded. Physical IPU7 capture
uses in-tree drivers and libcamera/PipeWire; its camera path needs no optional
v4l2loopback module.

The refreshed [Fedora prerequisite probe](https://github.com/closure-labs/finite/actions/runs/38314613864)
at `0759a023ecda` confirms all 16 implemented floors remain available. Its inventory
parser passed and it reported policy `blocked`, with no probe error: approved
AnyIO remains 4.13.0, msgpack 1.1.2 and rclone 1.74.3, below the corresponding
4.14.2, 1.2.1 and 1.75.1 fixes. Their publishers must supply approved fixes or
exact authenticated backport proof. No RPM-owned Python overlay is used.
Other Go-owning executables need publisher rebuilds and fresh module evidence;
installing a newer compiler does not repair shipped binaries. Windows/32-bit and
old-kernel findings remain narrow applicability leads requiring exact artifact
evidence and policy review, with no new waiver applied.

The refreshed advisory boundaries matter for desktop exposure:
[AnyIO](https://github.com/advisories/GHSA-82r6-8w77-94w6) describes TLS hostname
spoofing on redirected connections to non-ASCII hostnames, which can affect
clients consuming untrusted network destinations.
[msgpack](https://github.com/advisories/GHSA-6v7p-g79w-8964) describes an
out-of-bounds read/crash after catching an Unpacker error and continuing to use
the unpacker; assess the actual consumer's error handling and attacker input.
The rclone [RC per-server auth-proxy bypass](https://github.com/advisories/GHSA-p569-5gjg-9cmj)
and [serve S3 auth-proxy signature bypass](https://github.com/advisories/GHSA-xwwr-4h3p-r22c)
need exact listener/configuration evidence. Presence of rclone alone does not
prove these server modes are exposed. These mechanisms guide prioritization;
they do not change scanner policy or waive the unavailable fixes.

## Remaining sequence and verdicts

1. Complete authorized explicit ZFS package removal across all four profiles and
   focused regressions preserving unrelated inventory, signatures and ownership.
   Run cheap source/Nix checks before one representative changed copy, then all
   four integration builds. The next 301 testing choice is still unapproved;
   retain 300/stable policy and its open October XFS/AMD gap.
2. Use the hosted local-candidate helper for one representative patched OCI copy.
   Its 17 fixtures pass; its first hosted native scan is pending. Authenticate
   layout blobs, profile and source identity, reuse production scan policy, and
   compare all baseline findings. The unpublished copy is diagnostic evidence;
   it has no release signature or publication authority. Production verification
   rejects explicit diagnostic markers before release processing. Thirty policy
   fixtures pass, covering those boundaries and the new non-waivable KEV gate.
3. Review persistent/new/not-observed findings and positive applicability evidence.
   Preserve unknowns and current policy; not-observed is never automatically fixed.
4. Build and inspect all four changed profiles only after cheap checks and useful
   representative evidence. Draft PR #144 exists; its final source revision and
   new integration results are pending slots in the evidence ledger.
5. Require fresh digest-bound native scans, isolated signing and affected-profile
   Secure Boot/LUKS install, upgrade and rollback qualification before eligibility.

- Source/build: historical all-profile validation and source contracts passed;
  the new ZFS-removal source needs fresh focused/Nix checks, patched-copy scan
  and final all-profile integration.
- Vulnerability clearance: blocked. Diagnostic Go evidence and package
  transactions do not replace a complete fresh candidate scan or close findings.
- Release eligibility: ineligible until all applicable security and boot gates pass.

Heavy builds, full scans/inventories and VMs remain hosted. Diagnostic subprocesses
use bounded time and separate 2 GiB limits with swap disabled. No Go scanner or
compiler is added to the ordinary image-tool closure. Temporary validation refs
retain read-only permissions and no signing/App secrets; remove them after saving
evidence. Reuse valid evidence and cancel only demonstrably doomed or redundant
runs.

## Historical ZFS discovery and current support decision

[The representative patch attempt](https://github.com/closure-labs/finite/actions/runs/38314613864)
at `0759a023ecda` authenticated its inputs and applied the RPM/Tailscale floors,
then correctly refused to delete `extra/zfs/spl.ko` owned by retained
`kmod-zfs-2.4.4-1.fc44`. It produced no new image digest or native scan. Earlier
passing transactions used an older pruning implementation and do not establish
that retained ZFS modules remained functional.

[The current-base ownership probe](https://github.com/closure-labs/finite/actions/runs/38315879860)
passed and confirms both approved current bases also retain the same old-kernel
ZFS RPM and owned module. The
[official module matrix](https://github.com/ublue-os/akmods/blob/main/images.yaml)
and [Bluefin installer](https://github.com/ublue-os/bluefin/blob/main/build_files/base/03-install-kernel-akmods.sh)
identify inherited ZFS support. No authenticated matching required-kernel ZFS
bundle was identified at that observation. The user has since explicitly
authorized removing host ZFS from all four profiles. The product direction is
now removal of reviewed ZFS package names, while keeping the unrelated-package
inventory and file-ownership guards. There is no current wait for a matching
ZFS module or another ZFS permission question. The preexisting next-profile blanket pruning now uses the same shared
ownership guard; its earlier 25 generic and ten next fixtures passed, including
refusal to delete retained ZFS modules, unknown files or failed probes. Those
results predate the newly authorized removal source and are historical evidence.

The next transaction also snapshots its complete RPM inventory and checks it
immediately after each DNF operation. The earlier guard allowed only runtime
kernels and approved development/virtual-camera cleanup names, catching accidental
ZFS erasure. The new implementation permits only the additional explicitly reviewed ZFS
names; unrelated erasure remains forbidden. Thirty generic and fourteen next
fixtures pass for authorized removal and unrelated-package preservation.
Hosted transactions must establish actual dependency compatibility.

## Historical source validation and new working source

[Hosted source contracts](https://github.com/closure-labs/finite/actions/runs/38317182847)
passed exact source `4bc79ded4fcf4cfe0d426f9d0bca2f03800b34db`. This is useful
historical evidence; it does not cover the newly authorized ZFS-removal code.
[Draft PR #144](https://github.com/closure-labs/finite/pull/144) targets main.
Its last posted head starts `9a65`; working source is changing and needs new
focused/source contracts, pinned Nix checks, all four image builds and one useful
changed-candidate native scan. Keep the PR draft until those results are bound to
its exact final source. No new-source scan or boot success is claimed yet.

Host ZFS filesystem support is removed by the new source for all four profiles;
assembled-image validation is still pending. The
user's separate FreeBSD VM storage setup is an alternative to investigate, not
validated installation guidance and not a replacement for the host root filesystem.
It does not waive desktop security, signing, or boot qualification requirements.
The next 301 testing-update preference remains unapproved; current 300 and the
strict stable-tag policy stay pinned while their October XFS/AMD gap remains open.

## Resolving the remaining blockers

The default is conservative: it blocks fixable High/Critical scanner matches and
known-exploited findings, not every CVE. "Fixable" means an advisory lists a fix;
it does not prove an approved Fedora/vendor package is available or that every
matched executable is exploitable. Some matches therefore need remediation and
others need exact applicability review. Keep the strict digest, inventory,
freshness, signature and boot boundaries; lowering the global severity threshold
or treating SELinux as universal confinement would obscure genuine desktop risk.

| Remaining scope | Concrete resolution options | Required proof |
| --- | --- | --- |
| AnyIO / msgpack | Approved fixed Fedora RPM; authenticated owning-RPM backport/rebuild; remove an optional consumer only after dependency review | Actual owning packages, patched source and shipped bytes; msgpack consumer behavior after an Unpacker error; supported desktop use cases remain intact |
| rclone | Approved fixed owning RPM/backport; remove it if optional after dependency/use-case review; reviewed exposure controls for the two server advisories | RC auth-proxy and serve S3 configuration/listeners, supported command paths and every affected location; absence of a default listener alone is not an artifact-wide fix |
| Embedded Go in container/development/VPN tools | Publisher rebuild with required compiler and module fixes; authenticated compatible source/backport | Inspect actual rebuilt owning executables and all matching live/OSTree locations; compiler installation alone does not rebuild them |
| Next kernel 300 | Wait for a stable security-fixed same-stream update; separately review the exact 301 testing exception if explicitly authorized | Five authenticated Fedora45 RPMs, required modules, initramfs and boot qualification; testing gating/request-stable are not stable publication |
| Native match applicability | Verify exact platform, source/backport or disabled/absent affected functionality; propose a narrowly scoped exception only if positive evidence supports it | GO-2026-6604 Windows and historical CVE-2020-27815 JFS are leads, not dispositions; cover every matched artifact/path and supported profile/use case |
| Changed-source qualification | Finish focused/Nix checks, one useful patched-copy scan and four-profile integration, then production security/signing/boot gates | Exact revisions and manifest/results; an unpublished diagnostic pass is not release qualification |

The first inexpensive investigations after the current candidate result should
be msgpack's actual consumers/error handling and rclone's dependency/configuration
paths. The published msgpack workaround discards/recreates an Unpacker after an
error; applying it requires proof of the actual affected consumer. Determine
whether the optional consumers can be removed without removing required desktop
or container features. For rclone, inspect which server modes are enabled or
supported before choosing controls or removal. AnyIO's redirected non-ASCII TLS
hostname issue remains a client trust concern requiring an owning-package fix or
exact affected-call-path evidence. Do not classify all server advisories as exposed
by default, or all process-local crashes as harmless.

The existing exception format requires an exact image digest, exact component
PURL (or artifact ID), advisory, approvedAt/expiresAt, reviewedBy and reason, with
a maximum 30-day review window. Exceptions are reviewed committed policy changes,
not runtime workflow inputs. The schema does not independently encode paths,
platforms or listener configurations: a component/advisory exception covers every
matching occurrence in that digest, so the review must establish the claim for
all of them. Other profile/new-build digests require their own review. Evidence
links, artifact hashes, source patches and exposure assumptions belong in the
review rationale. No exceptions are active or introduced by this assessment.

Known-exploited findings now remain blocked despite an ordinary exact exception
when the KEV gate is enabled, including related aliases and ignored matches;
30 focused policy fixtures pass. Exceptions cannot repair stale/incomplete native
evidence, unknown symbol coverage, signature failures or failed boot contracts.
Missing symbols in the diagnostic probe are not proof of non-applicability.

The in-progress representative run
[38321177037](https://github.com/closure-labs/finite/actions/runs/38321177037)
uses frozen source `371b7f17`; do not claim its outcome before completion. The
44 kernel and 12 contract fixtures passed at source `c295`, while the later
KEV hardening has its separate 30-fixture result. Historical source success does
not establish the latest all-profile build result. Once the new native result is
available, compare persistent/new/not-observed findings and prioritize owning
packages rather than repeating unchanged scans or treating trace counts as
unique vulnerabilities. Source/build validation, vulnerability clearance and
release eligibility remain independent verdicts. No new kernel testing approval,
blanket waiver, unsigned/self-signed remediation source or publication is granted.
