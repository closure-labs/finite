# Release eligibility sequence

Finite uses Bluefin/bootc with Nix/Home Manager and Jujutsu. This sequence starts
from externally merged policy PR145 at `7dba29d3da8770b11ae633545a53854ba10ee353`.
Main then independently merged the same signed upstream digests in
[PR146](https://github.com/closure-labs/finite/pull/146) at
`cbaf82645aa1e437fe42157ab5712869f74219ba`; this remediation change was rebased
with JJ and preserves that update. It covers all four supported profiles and their container/development tools.
Source validation, vulnerability clearance and release eligibility remain separate.

## Implemented work

- Refresh the two standard profiles to the new approved signed Bluefin stable
  digest observed by38334919442. Newly announced stable-20261013 then advanced
  DX to the signed a41cf1eb digest verified by38336166342; update both DX profiles.
  Authenticate sources first;
  the source refresh grants no vulnerability clearance.
- Add installed-only Curl/libcurl floors at the signed stable Fedora44
  `8.18.0-12.fc44` backport. Preserve the installed full/minimal library variant,
  signing sources, architectures and protected boot stack. There are19 configured
  floors; absent packages are not installed merely to satisfy a floor.
- Refresh prerequisites against approved Fedora/updates sources. AnyIO4.14.2 and
  rclone1.75.1 remain unavailable in the recorded query. Msgpack's unavailable
  routine fix remains visible and no longer blocks this metadata readiness check.
  Availability never grants vulnerability clearance; Critical/KEV/source holds
  still require native policy evaluation.
- Collect bounded positive ELF/Go platform, main-package and byte-hash evidence
  while the scanner already has the authenticated extracted filesystem. Historical
  paths are selectors only. No extra pull, compiler installation, binary execution
  or vulnerability scan is introduced. Missing, malformed and symlinked files
  remain unknown; the collector grants no dispositions.
- Add an explicit manual channel selector to Build Finite. `automatic` preserves
  existing push/PR/merge-queue/reconciliation behavior. A selected channel still
  requires all checks, security, isolated signing and boot qualification. Its
  complete successful run can satisfy the existing durable-release whole-run
  requirement without forcing a held Next profile into that same run.

- Add guarded reuse of a trusted main candidate after a policy-only review.
  The image retains its original source revision and exact digest; current checks,
  security policy, signing and boot qualification use the current revision.
  Verify the original successful build, artifact hash, runtime identity and source
  ancestry. A changed runtime input requires rebuilding; this path cannot reuse
  the pre-Curl candidate for the new floors.
- Add an opt-in, single-channel diagnostic scan on a validation branch. It uses
  the image already assembled by that job and never publishes or signs it.
  Native evidence and positive file proofs stay on the hosted runner; scanner
  errors remain distinct from policy blockers. Pinned scanner tools are prepared
  only for requested diagnostics. Tiny actual umoci smoke38339665069 passed:
  preserve configuration/layer bytes while deriving local OCI media-type metadata
  and retain original digest evidence. This gate precedes diagnostic image work.

The [sequence evidence](release-eligibility-evidence-2026-10-12.json) records
source hashes, approved publisher metadata, transaction and retained artifact
bindings. The signed Curl transaction and disconnected repeat succeeded in
run38331968520; its wrapper then failed because ripgrep was absent. Recovery
[38332614606](https://github.com/closure-labs/finite/actions/runs/38332614606)
verified those exact artifacts, changed NEVRAs, source RPM, integrity and protected
inventory without another transaction, pull, build or scan. Do not describe the
original overall workflow as passed.

## Remaining work and stop conditions

1. Finish hosted source checks and affected-profile image validation for the new
   Curl floors. Reuse existing benchmarks and source/build evidence where inputs
   are unchanged. No workstation Nix evaluation, image/SBOM parsing or VM work.
2. Reuse the complete candidate/native evidence from main run38330308713. These
   images predate the new Curl floors and collector. Bind each actual immutable
   candidate, source revision, input identity, upstream receipt and native hashes;
   compare completed findings with the retained baseline using the existing helper.
   Hosted summary38334371393 passed: Generic/Next retain121 blocking pairs each; development profiles retain179
   each and both Next variants retain the kernel source hold. Generic retains318 blocking and995 advisory records; no dispositions.
3. Review exact current artifact proof. GO-2026-6604 is positively Windows-only;
   every matching live and retained path needs positive current platform evidence.
   Apache2.4.68 source matches the publisher's fixed release; verify owning-RPM
   and shipped-file integrity before disposition. FreeRDP3.31.1 includes upstream
   guards. Signed reference proof38340338218 now binds all12 retained old-main
   objects to authenticated Fedora payload bytes; current candidate joins remain
   required. See
   [Critical review](desktop-critical-applicability-2026-10-12.json) and
   [Go review](desktop-go-applicability-2026-10-12.json). No disposition is active.
4. Apply additional compatible authenticated owning-package fixes or positively
   verified backports as available. Compiler defects and embedded x/mod/Go
   dependencies require separate actual rebuild/source proof. An installed new
   compiler, empty symbol output or default listener absence does not clear them.
5. Both Next profiles retain the reviewed kernel source hold: the official
   f45/f45-updates query still selected300. Await approved fixed stable source or
   a separately explicit testing decision, then validate signed payloads, modules,
   initramfs and boot behavior. Continue independent Generic work meanwhile.
6. Once the applicable risks and source holds clear, use exact complete production
   candidates: native fresh security pass, isolated image signing, applicable
   Secure Boot/LUKS fresh install/upgrade/rollback, then promotion. Prepare matching
   ISO/durable release evidence, the required fresh release security check and
   isolated release signing before review/publication.

Ordinary421 advisory pairs may remain under the approved upstream-maintenance
model. The historical121 diagnostic blockers are neither121 confirmed exploits
nor121 required upgrades, and none is automatically cleared by these code changes.
Known external package/source blockers have concrete publisher events; missing
applicability evidence remains a Finite review task. No merge or publication is
performed by this continuation.

## Owners and concrete unblock events

| Remaining item | Owner | Required event or evidence |
| --- | --- | --- |
| AnyIO TLS identity bypass | Fedora package maintainer / Bluefin | Signed compatible Fedora44 AnyIO4.14.2+ or documented backport; verify installed bytes and native result |
| rclone conditional authentication bypasses | Fedora package maintainer / Bluefin | Signed compatible rclone1.75.1+ or documented backport for both advisories; supported configured server paths remain in scope |
| Embedded Go, x/mod, x/crypto and x/net | Each owning binary publisher; Finite validates | Compatible signed owning binary rebuild/backport, actual current module/compiler metadata and all live/retained paths; installing a compiler is insufficient |
| Code shell-quote and Docker Buildx archive handling | Microsoft / Docker / Bluefin | Fixed supported dependency or specific source/backport and shipped-byte proof; newest release source still declares old dependencies |
| Retained FreeRDP / Apache / Windows-only Go scanner matches | Finite security reviewer | Complete current digest/component/alias/all-location join to signed reference bytes or positive platform/source evidence; missing proof stays unknown |
| Next kernel source hold | Fedora kernel publisher; Finite validates | Approved stable f45 source containing required fixes, authenticated RPM/module/initramfs evidence, then applicable boot qualification; no testing/cross-release substitution |
| Native scanner or collector errors | Finite CI maintainer | Correct cause, preserve error evidence and complete a useful changed candidate; never convert errors into policy passes |
| Signing, boot qualification and durable release | Finite release owner | Applicable exact candidate security pass, isolated signing, Secure Boot/LUKS fresh install/upgrade/rollback, matching ISO and fresh release gate |

SELinux enforcing is part of the supported desktop configuration. It does not
establish that TLS identity, authorization, malicious archive/file handling or
container escape defects are harmless. Ordinary upstream advisories remain
accepted under the approved policy; serious risks require applicable fixes or
specific positive evidence, not a universal suppression.
