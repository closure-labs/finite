# Generic kernel validation and remediation

[Metadata probe 38301720702](https://github.com/closure-labs/finite/actions/runs/38301720702)
confirmed all five Fedora 44 kernel packages at `7.2.9-201.fc44.x86_64` are available.
[Authentication probe 38302087723](https://github.com/closure-labs/finite/actions/runs/38302087723)
verified their exact payload hashes, package identities and Fedora 44 signatures in
an isolated key database. Kernel payload availability is therefore established.
[Retained evidence](generic-kernel-prerequisite-evidence-2026-10-12.json) records the
public-key identity, all payload hashes and precise source revisions.

[Read-only compatibility probe 38302232585](https://github.com/closure-labs/finite/actions/runs/38302232585)
then authenticated the pinned generic Bluefin base and examined actual installed
dependencies. `kmod-v4l2loopback-0.15.4-1.fc44.x86_64` requires exactly
`kernel-uname-r = 7.2.5-200.fc44.x86_64`. Its companion `v4l2loopback` requires that
kmod capability. The queried approved Fedora repositories provide no matching
replacement. `kernel-devel-matched` also records exact inherited kernel/devel
requirements. The assume-no solver reports conflicting kernel-core packages and
skips the proposed kernel; its exit 0 and `Nothing to do` do not mean an update
worked. No packages were installed or removed.

The concrete blocker is compatible signed module/development packages. Preserve
generic virtual-camera and DX development capabilities. The next-profile cleanup
policy is a separate profile decision; copying its removal list into generic
remediation would remove existing capabilities. No generic kernel replacement or
source-built/self-signed module is introduced to force a passing transaction.

### Implementation after dependency prerequisites change

1. Obtain an authenticated matching Fedora 44 kernel/module package set or a
   reviewed authenticated Bluefin base that includes it; record every inherited
   external module and its owning RPM/dependency.
2. Pin exact payload identities/hashes and the reviewed signing key. Authenticate
   every package before any mutation. Preserve all non-kernel packages or update
   them through approved matching-release signed replacements.
3. Install the complete kernel without erasing runtime/development features. Verify
   required modules, signatures and indexes before removing recorded stale kernel
   packages or module directories. Regenerate initramfs before profile metadata.
4. Add focused failure fixtures and run a real hosted bounded transaction; build
   only both affected generic profiles. Add tested generic-only selection and
   input-identity handling before introducing generic source files, because the
   current shared/script input hash would otherwise rebuild next profiles.
5. Once overall scan readiness changes, scan one new immutable image digest and
   compare all baseline findings. Require isolated signing and Secure Boot/LUKS
   boot/upgrade/rollback qualification before release.

This plan concerns the generic profiles. The next profiles use a separately pinned
Fedora 45 kernel and in-tree IPU7 camera drivers with libcamera/PipeWire.
[PR #140](https://github.com/closure-labs/finite/pull/140) tracks the separate
Tailscale and Fedora RPM remediation. Source prerequisites are partially
verified; kernel compatibility, vulnerability clearance and release eligibility
remain blocked on the exact dependencies above.
