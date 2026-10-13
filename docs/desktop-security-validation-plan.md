# Desktop security validation

The active [release eligibility sequence](release-eligibility-sequence.md) starts
from externally merged PR145 and records new remediation/proof work. The sections
below retain the completed desktop-policy validation history.

This continuation covers all four Finite profiles, their desktop applications,
development tools and container runtimes. Finite uses Bluefin/bootc with Nix/Home
Manager. Changes use Jujutsu in isolated security workspaces. The
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

## Current status

[PR #144](https://github.com/closure-labs/finite/pull/144) implementation head
`fd64b32f4667b3f366b2eafcba5c6ed9ba6431dd` passed all four image builds and runtime
inspections, documentation, pinned Nix/source contracts and the CI gate in
[run 38322036024](https://github.com/closure-labs/finite/actions/runs/38322036024).
The tested PR merge revision is `ed7e5151f51445f4cd5e64715b6e9cef80115600`, distinct
from the implementation head. All four local image identities and artifact hashes
are recorded in the ledger. Publication was skipped; these are Docker image IDs,
not published manifest digests. No new merge, signing or VM boot result is claimed.

The user approved the [upstream-maintained-risk policy](desktop-risk-policy.md):
ordinary inherited findings remain advisory under an independently authenticated
baseline, while KEV, reviewed serious risks and untriaged Critical findings block.
There are 45 serious groups covering 102 aliases and no active proof dispositions.
The policy-only follow-up is [PR145](https://github.com/closure-labs/finite/pull/145).
Retained-evidence evaluation38327429782 completed; final source checks passed38327424786. The Next 300 XFS/AMD source gap remains an explicit release hold.

[The unpublished diagnostic scan](https://github.com/closure-labs/finite/actions/runs/38321177037)
completed once: 261 distinct old-strict component/advisory pairs, 725 raw blocking
records and zero observed KEV blocking records. This is the historical severity
policy result, not a new-policy verdict. [Recovery run 38324348014](https://github.com/closure-labs/finite/actions/runs/38324348014)
passed semantic configuration binding, ordered 89-layer identity, SBOM binding and
exact comparison recomputation without rebuilding or rescanning. The Docker/OCI
configuration bytes differ; their original-byte difference remains unknown.
Recovery qualifies retained diagnostic evidence only, not a production signature,
complete recipe build or boot result. The new risk evaluation completed blocked
in run38327429782; exact outcomes are recorded below.

The policy-only source passed independent integration review and 212 focused tests
(66 policy, 43 upstream, 35 reliability, 23 local-candidate, 16 selection,
14 comparison, 11 approved-baseline and four delivery fixtures) at policy source
`e599d99f10e6`; hosted checks passed38327424786 at tested merge79715d7b. The corrected identity self-hash/exclusion
algorithm causes one computed-identity migration requiring main reconciliation
once. Subsequent policy-only edits retain stable identity. Retained fd64 matrix
and unpublished native identities must stay exactly as originally observed.

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
  Approved removal now passes 30 generic/14 next regressions, a representative
  transaction/offline repeat in run 38321177037 and all-four build/runtime
  contracts in run 38322036024. Both generic recipes now
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
they guide the new serious-risk registry without establishing that any shipped
consumer is fixed or eligible for a disposition. Msgpack remains advisory under
the approved upstream-maintenance model unless separate serious-impact or KEV
evidence changes its classification.

## Remaining sequence and verdicts

1. Completed hosted policy-only source checks38327424786. Retained authenticated evidence has
   already been evaluated in run38327429782; reuse that completed result and
   passing builds, transactions and benchmarks. No unchanged image scan.
2. Bind remaining serious and untriaged Critical findings to all observed aliases,
   exact components and locations across supported profiles/use cases. Implement
   only verified compatible remediations, or review positive artifact proof for a
   narrowly scoped disposition. Preserve unknown reachability and probe errors.
3. Resolve the Next 300 source hold through approved stable promotion of a fixed
   same-stream kernel, or a separately explicit reviewed testing decision. Keep
   the current lock and stable-tag policy until then; no cross-release substitute.
4. Require production digest-bound security, isolated signing and affected-profile
   Secure Boot/LUKS install, upgrade and rollback gates before release eligibility.
   This continuation authorizes implementation, validation and PR updates only.

- Source/build: **PASS** PR #144 head `fd64b32f4667b3f366b2eafcba5c6ed9ba6431dd`,
  tested merge `ed7e5151f51445f4cd5e64715b6e9cef80115600`, run 38322036024; all four
  builds/runtime, documentation, Nix/source checks and CI gate passed. Policy source `e599d99f10e6` also passed run38327424786 as tested merge
  `79715d7b413e910dcf6c4ae7d26a95e6849dcbbb`; no image inputs changed.
- Vulnerability clearance: **BLOCKED** after completed policy evaluation38327429782:
  121 blocking pairs (95 reviewed serious risks and26 untriaged Critical),421
  advisory pairs,0 observed KEV and0 exceptions. Historical old-strict counts
  remain separate; unknown applicability and retained-object reachability persist.
- Release eligibility: **ineligible**. Next source hold, current security review,
  production signing and applicable boot qualification remain unmet.

Heavy builds, full scans/inventories and VMs remain hosted. Diagnostic subprocesses
use bounded time and separate 2 GiB limits with swap disabled. No Go scanner or
compiler is added to the ordinary image-tool closure. Temporary validation refs
retain read-only permissions and no signing/App secrets; remove them after saving
evidence. Cancel only demonstrably doomed or redundant runs.

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
The representative transaction/offline repeat and all-four image/runtime checks
now establish the tested dependency/build compatibility. VM boot qualification
is separate.

## Completed source validation

[Historical source contracts](https://github.com/closure-labs/finite/actions/runs/38317182847)
passed `4bc79ded4fcf4cfe0d426f9d0bca2f03800b34db` before the approved ZFS removal.
Later PR #144 head `fd64b32f4667b3f366b2eafcba5c6ed9ba6431dd` passed all four image
build/runtime and pinned source/Nix checks in run 38322036024 at tested merge
`ed7e5151f51445f4cd5e64715b6e9cef80115600`. The earlier result is retained history;
the later result validates the changed source. Policy-only source checks and PR
binding remain a separate continuation; no repeated image matrix is needed solely
for this evidence reconciliation.

All four assembled-image contracts establish absent host ZFS tools/modules:
explicitly removed `kmod-zfs`, `zfs` and `python3-pyzfs`, retaining shared libraries
where unrelated-package preservation requires them. The user's separate FreeBSD
VM storage proposal is not validated installation guidance or a host-root
replacement. These build contracts do not waive signing or boot qualification.
Next remains 300 under the stable-only policy; no 301 testing approval is assumed.

## Resolving the remaining blockers

The approved model assigns routine inherited risks to verified upstream maintenance
and retains serious desktop/container blockers. It replaces the historical blanket
fixable High/Critical rule; it does not claim every upstream program is fixed or
trust Finite's kernel/Cosign overrides automatically. Read the full
[risk policy](desktop-risk-policy.md) for the 45-group/102-alias registry and sources.
KEV cannot be waived, serious alias groups block independently of severity and fix
availability, and untriaged Critical findings require complete artifact review.
No proof disposition or blanket suppression is active.

| Remaining scope | Concrete owner/event | Required proof |
| --- | --- | --- |
| Policy source qualification | Finite final hosted source checks38327424786 passed; retained evaluation38327429782 is complete and blocked | Exact source/check binding; preserve native hashes and independently authenticated baseline; no diagnostic promotion |
| AnyIO / rclone serious boundaries | Owning Fedora/vendor publisher supplies compatible signed fixes or authenticated backports; Finite verifies affected call paths | Actual shipped packages/files; AnyIO TLS hostname use; rclone RC/S3/FTP/restic configuration and all supported command paths. Default listener absence is not artifact-wide proof |
| Embedded Go / compiler serious findings | Owning package, Tailscale or Sigstore publisher rebuilds; Finite authenticates actual executables | Compiler and embedded-module proof for live and retained locations; an updated installed compiler does not repair existing binaries |
| Critical applicability | Finite artifact review supplies complete positive OS/function/impact proof | Windows GO-2026-6604 and resource-exhaustion Criticals remain leads, not dispositions; cover every alias/path/profile before a typed review |
| Retained OSTree content | Finite ownership/reachability review resolves old ELF objects | Old FreeRDP/HPLIP/libX11/sudo locations are known; live RPM floors are installed, but retained object reachability/backport status remains unknown |
| Next 300 kernel | Fixed same-stream source reaches approved stable tag, or user explicitly approves a reviewed testing source | Five exact signed Fedora45 runtime RPMs, required IPU7/modules/initramfs, and boot qualification; testing gating/request-stable is not stable publication |
| Production qualification | Finite delivery and boot validation after risk prerequisites support it | Exact recipe-built immutable digest, production policy, isolated signer and affected-profile Secure Boot/LUKS install/upgrade/rollback |

The recovered candidate maps older FreeRDP 3.31.1, HPLIP 3.26.4, libX11
1.8.13-1 and sudo 1.9.17-8 ELF artifacts to retained
`/sysroot/ostree/repo/objects` paths. The live RPM catalog reports FreeRDP/WinPR
3.32.1, HPLIP 3.26.6, libX11 1.8.13-3 and sudo 1.9.17-10 fixed floors. This is
positive location/cataloger evidence, not proof that every retained object is
unreachable or that scanner matches are false positives. Exact artifact IDs,
versions, paths and hashes are retained in the ledger; no finding is automatically
closed and not-observed remains distinct from fixed.

The new typed `reviewedDispositions` format requires exact aliases, digest,
versioned component, platform, every canonical in-image location, disposition,
reason, official sources, positive evidence, reviewer/time and expiry within
30 days. New aliases or uncovered paths invalidate narrower proof. `routine`
cannot waive serious groups; KEV remains nonwaivable. The legacy exception format
is historical and does not provide the new risk-mode proof boundary. Missing
symbols, SELinux labels or a successful helper process do not establish absence.

The unchanged diagnostic candidate's native scan completed at
`371b7f17bc02ab84da119e73becbdb4d6c87e2bc` in run 38321177037. Recovery run
38324348014 validates supported configuration/platform fields, ordered 89 rootfs
diff IDs, patch labels and SBOM hash and reproduces the comparison exactly:
186 persistent, 75 new and 95 not-observed pairs; 65 new pairs reuse an advisory
already present in the baseline. Original layer bytes were hashed before
extraction; recovery did not rehash absent layer blobs. Original raw Docker config
bytes were not retained, so semantic equivalence does not establish byte equality.
The diagnostic copy remains unpublished and release-ineligible; it is not the
four-profile recipe matrix or a production signing result.

Reuse these observations for the next policy evaluation and ownership review.
Ordinary advisory maintenance can continue independently of the Next source hold
or a blocked serious item. No new testing approval, merge or publication is granted.



### Msgpack consumer follow-up

Retained approved standard/DX package inventories contain Borgbackup 1.4.5-1.fc44
and python3-msgpack 1.1.2-2.fc44. This identifies a consumer lead, not a complete
reverse-dependency inventory or proof of candidate shipped source.
[Borg's exact 1.4.5 source](https://github.com/borgbackup/borg/tree/1b7d3271d2e59e27c61815ff36a29e06a9767e13)
recreates the Unpacker after parse errors in archive deletion and resynchronization,
consistent with the official msgpack workaround. Its persistent RPC unpacker and
exception cleanup/rollback path still require investigation for reuse after a
malformed authenticated-server response. This is a potential application DoS
path, not established RCE, privilege escalation or package-wide mitigation.

[The Fedora packaging source](https://src.fedoraproject.org/rpms/borgbackup/raw/bd24f304c025466ee6dc9b04f2ce864c640f7333/f/borgbackup.spec)
shows only a documentation-theme patch at the reviewed commit. Before disposition,
bind the candidate's shipped Borg/msgpack files to authenticated owning RPMs,
inventory other consumers across supported profiles, and test the RPC cleanup
boundary in a bounded hosted subprocess. Preserve the unknown until that proof;
no msgpack exception or speculative consumer patch is implemented.

Msgpack’s process-DoS advisory remains visible under the approved upstream-maintenance
model; consumer follow-up is useful maintenance evidence, not a blanket release
block solely because the historical severity policy labeled it High. No shipped
consumer fix or artifact disposition is inferred from the upstream source review.

PR #144 was merged externally at `bd78c07f25412484d90310f76e5dd0807014ebe1`
while the approved policy follow-up was prepared. That follow-up targets the new
main revision; this continuation did not merge or publish. The unchanged runtime
tree retains its exact fd64 build evidence.

## Approved policy validation outcome

[PR145](https://github.com/closure-labs/finite/pull/145) targets externally merged
main. Policy source `e599d99f10e6` passed 212 focused tests and independent integration
and parser reviews. Final hosted source checks passed run38327424786.
[Policy evaluation38327429782](https://github.com/closure-labs/finite/actions/runs/38327429782)
completed successfully with a **blocked** security verdict:121 blocking pairs
(95 serious,26 untriaged Critical),421 advisory pairs,0 KEV and0 exceptions.
It reused the same native immutable manifest and raw evidence without rescanning.
See [exact evaluation](desktop-risk-evaluation-2026-10-12.json) and
[remaining file-level blockers](desktop-risk-blockers-2026-10-12.json).

The expanded observation scope and104 disposition changes reflect the approved
policy decision, not newly introduced vulnerabilities or successful package fixes.
The95 nonobserved baseline pairs remain review-required. The Generic patched copy
is diagnostic and unsigned; applicable production scan/signing/boot gates remain
unmet. Both Next profiles retain the independent reviewed kernel source hold.
Source/build evidence remains separate from vulnerability clearance and release
eligibility. No merge, publication or testing-kernel approval was performed here.

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
