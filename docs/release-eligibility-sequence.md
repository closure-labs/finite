# Release eligibility sequence

> Historical record: earlier four-profile release sequence. For current operations, use
> [CI and releases](ci-and-releases.md) and [security review](security-review.md).
> See [reports](reports.md) for dated evidence and related work.

Current execution order: [remediation and independent release sequence](release-implementation-sequence.md).

Finite is a Jujutsu (JJ) repository using Bluefin/bootc with Nix/Home Manager;
it is not NixOS. This sequence covers all four profiles and container tools.
It began at externally merged PR145, `7dba29d3da8770b11ae633545a53854ba10ee353`.
PR146 then independently merged the same verified new Bluefin stable digests at
`cbaf82645aa1e437fe42157ab5712869f74219ba`; the remediation branch incorporates it.

## Completed implementation and validation

[PR147](https://github.com/closure-labs/finite/pull/147) passed every source,
documentation, Nix/runtime check, all four image builds/runtime inspections and
the CI gate in [38342366434](https://github.com/closure-labs/finite/actions/runs/38342366434).
Validated head: `68fbf8759df3208dc6879640aa7d211d9162addf`. The proof/evidence follow-up [PR148](https://github.com/closure-labs/finite/pull/148)
is stacked on this validated runtime change. Source/docs/Nix/payload checks and
CI gate38349399433 passed; dependency selection skipped redundant image work.

- Apply installed-only signed Fedora44 Curl/libcurl floors at `8.18.0-12.fc44`.
  Preserve full/minimal variants, approved sources, architectures and protected
  boot inventory. There are 19 floors; absent packages are not added for a floor.
  Signed transaction, integrity and disconnected-repeat evidence was recovered
  in run38332614606 after the original wrapper's missing-ripgrep error.
- Support an explicit manual channel and guarded unchanged-candidate reuse.
  Retain the original image source revision/digest; use the current qualification
  revision and policy. Require trusted successful origin build/artifact hashes,
  ancestry, runtime identity and current main/channel state. Changed inputs require
  rebuilding. Security, isolated signing and applicable boot gates remain required.
- Add opt-in unpublished diagnostics that reuse the assembled image, bounded
  Go/ELF and RPM byte probes, and original-digest extraction evidence. Derive only
  local OCI media-type metadata; preserve configuration/layer bytes. Optional
  scanner tools and a tiny actual umoci smoke precede requested diagnostics.
  Ordinary image-tool setup remains unchanged; no benchmark repeats.
- Both changed standard/DX diagnostics completed with valid policy-blocked
  evidence in38341281199/38341284379 at source
  `1d347b7456b0cf64d4372cc0e7a562a9e63eb45b`. Their builds/runtime inspections pass.
  Reuse the four new upstream-based registry candidates from main38340112122 too.
  Hosted compact summary/comparison38344754471 passed without another scan.
- Signed FreeRDP, Podman and HTTPD reference checks passed in38340338218,
  38344182246 and38344687698. Current HTTPD2.4.69/FreeRDP3.32.1 differ from the
  historical references; their absent current matches are not automatically fixed.
  No HTTPD/FreeRDP disposition was added.
- Independently review 36 exact current Go/Podman nonapplicability scopes and
  15 SSH large-write-loop availability-risk acceptances, all expiring after14days.
  Every scope binds digest, component, aliases and all current locations.
  Positive Linux byte/platform proof supports Windows-only Go6604 treatment;
  authenticated fixed Podman5.8.7 payloads support three main-module treatments.
  Primary Go5020 describes an empty-packet loop after a caller supplies more than
  4GiB: accept that availability risk under the approved desktop policy. A stalled
  writer retains its caller buffer; CPU/network effects and unproved global host
  resource ceilings remain explicit. This is risk acceptance, not a fix.
- Final full-native reevaluation38348146097 reproduced all original results and
  preserved observations. Standard profiles retain87 blocking pairs/266 records;
  development profiles retain135 pairs/481 records. Both Next profiles also retain
  the kernel source hold. The comparison helper preserves non-observations and
  disposition changes as review data rather than claiming fixes.
- 401 focused fixtures pass. Independent review approved the source, references
  and all51 scopes. The policy test harness now reads its temporary fixture from
  a file after the larger ledger exceeded the OS argument-size limit.

The [evidence ledger](release-eligibility-evidence-2026-10-12.json) binds exact
revisions, runs, image digests, raw/report hashes and decisions. The
[current blocker/ownership ledger](current-desktop-risk-blockers-2026-10-12.json)
maps every remaining component/advisory scope in all four registry candidates to
shipped paths, owning RPM metadata or explicitly unknown ownership. Retained-file
ownership relationships use exact content equality; they do not independently
verify a package signature or resolve its vulnerabilities.

## Independent channel qualification

The user approved qualifying channels independently. Continue security remediation
for all four profiles, but a generic channel may proceed when its own exact
candidate security, signing and boot gates pass while Next awaits its source fix.
Use the existing manual channel selector; a passing build or another channel's
qualification cannot clear that candidate. This continuation does not merge or
publish a release.

## Remaining owners and concrete unblock events

| Item | Owner | Required event or evidence |
| --- | --- | --- |
| AnyIO TLS identity bypass | Fedora/Bluefin package maintainers | Compatible signed AnyIO4.14.2+ or specific backport; verify shipped files and native result |
| rclone conditional authentication bypasses | Fedora/Bluefin package maintainers | Compatible signed rclone1.75.1+ or specific fixes for both advisories; supported configured server paths remain in scope |
| Embedded Go/x/mod/x/crypto/x/net/gRPC and container libraries | Owning binary publishers identified in the ledger | Compatible signed binary rebuild/backport with the listed actual module/compiler fixes at every live/retained path, or specific reviewed source/byte/caller proof |
| Cosign and Tailscale | Sigstore and Tailscale | Authenticated compatible owning-binary releases/rebuilds with actual fixed embedded code; latest recorded releases3.1.3/1.104.1 alone do not establish clearance |
| Code shell-quote and Docker Buildx archive handling | Microsoft/Docker/Bluefin | Fixed supported dependencies or specific backport and shipped-byte proof; current official release sources still declare old dependencies |
| Go5017 connection leak / Go6612 HTTP2 memory accounting | Owning publishers; Finite reviews impact | Actual fixes or positive lifetime/aggregate stream/connection/process resource-bound proof. Closed connections and default listeners do not prove safety |
| Next kernel source hold | Fedora kernel publisher; Finite validates | Approved stable f45 source with required fixes, authenticated package/module/initramfs evidence and boot qualification; no testing or cross-release substitution |
| Missing owner/backport/applicability evidence | Finite security reviewer and relevant publisher | Authoritative owning source/reference mapping and complete current artifact proof; unknowns remain blocked |
| Production and durable-release qualification | Finite release owner | Applicable current exact-candidate security pass, isolated signing, Secure Boot/LUKS install/upgrade/rollback, matching ISO evidence and fresh release gate |

Reuse approved publisher queries38331234974/38336026926 and official source
reviews. Current core owning-package inventory equals latest versions in the
recorded Fedora query; package versions alone do not fix embedded modules.
AnyIO/rclone fixes and newer compatible development packages were unavailable in
those dated observations. A new approved publisher event warrants a fresh probe;
do not repeatedly poll unchanged sources or scan known-blocked unchanged images.

SELinux enforcing does not establish harmless TLS/authentication bypasses,
malicious archive handling, container escape or host-memory exhaustion. Ordinary
upstream risks remain visible accepted advisories. KEV and reviewed serious risks
remain blocking; no blanket suppression or installed-compiler shortcut was used.

Source/build validation: PASS for PR147 and the PR148 proof follow-up. Vulnerability clearance: BLOCKED. Release eligibility:
INELIGIBLE until applicable security, source, signing and boot/release gates pass.
No merge or release publication is performed by this continuation.

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
