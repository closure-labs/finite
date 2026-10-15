# Generic kernel validation and remediation

Historical plan: the later owner-approved [two-variant upstream kernel policy](upstream-kernel-variants.md) supersedes kernel replacement, ZFS removal and Next-variant instructions below. Preserve these observations as historical evidence; do not dispatch retired-variant work.

The user approved removal of optional generic virtual-camera support so the
Fedora 44 security kernel can replace the inherited exact-kernel module set.
This decision applies to `kmod-v4l2loopback` and `v4l2loopback`; it does not
authorize unrelated package removal or weakened trust/boot checks. The user has
also approved removal of host ZFS support across all four profiles. Explicit ZFS
package removal is implemented with the same unrelated-package and
file-ownership guards; 30 generic and 14 next fixtures pass. Hosted image
and dependency validation remain pending. Physical IPU7
capture on next profiles uses in-tree drivers with libcamera/PipeWire.

## Historical blocker and current implementation

[Metadata probe 38301720702](https://github.com/closure-labs/finite/actions/runs/38301720702)
and [authentication probe 38302087723](https://github.com/closure-labs/finite/actions/runs/38302087723)
established the five runtime Fedora 44 kernel payloads at `7.2.9-201.fc44.x86_64`.
The [read-only solver probe](https://github.com/closure-labs/finite/actions/runs/38302232585)
then showed that inherited v4l2loopback requires exactly `7.2.5-200.fc44` and DNF
can skip the replacement while exiting zero. These retained observations explain
the earlier blocker; they do not describe the authorized implementation's outcome.

The helper now pins seven signed payloads: five runtime kernel RPMs plus
`kernel-devel` and `kernel-devel-matched`. It installs the development pair when
inherited development packages require it. Exact hashes and Fedora 44 key identity
are recorded in `files/security/kernel-generic.json` and
[the current evidence ledger](desktop-security-evidence-2026-10-12.json).
Authentication of every required payload precedes optional-camera removal or
other mutation. Repository access is disabled during the bounded local-RPM
transaction, local signature checks are enforced, and unrelated packages must
retain identical inventory. No allowerasing, dependency bypass, self-signed
module or cross-release kernel substitution is used.

`7.2.9-201` includes substantive October AMD/XFS fixes. An available Universal
Blue module bundle for `7.2.9-200` does not establish equivalent coverage.
The [201 packaging change](https://src.fedoraproject.org/rpms/kernel/c/c2cdc6c5c0c6ccc0128613fc7c9d276ebaf870c7.patch)
and [XFS exchange-range fix](https://gitlab.com/cki-project/kernel-ark/-/commit/fa3bfc1343f7f3b1ebd873eee5e3e6618918f434.patch)
support the selected source. Filesystem-internal corruption cannot be dismissed
through a blanket SELinux argument.

## Evidence boundaries

[Run 38311107555](https://github.com/closure-labs/finite/actions/runs/38311107555)
at `5b961c8d` passed real transactions on the authenticated standard and DX bases,
including offline satisfied-floor repeats. This proves that helper revision's
package transaction; it is not a kernel boot test or a fresh vulnerability scan.

The newer pruning guard preflights every recorded stale tree and refuses owned
files, unexpected unowned files, symlinks and unknown directories before deleting
anything. It permits only a reviewed set of generated module files. Its 25
focused fixtures passed for the prior guard; the hosted attempt correctly
refused a retained ZFS owner. The user has since authorized host ZFS removal;
those earlier results do not validate the changed removal implementation.
Old trees are retired only after the replacement package set and module indexes
are verified. Both generic recipes now regenerate initramfs after replacement
and profile metadata, before finalization. RPM installation in a container does
not itself create this boot payload. Four recipe contracts and four initramfs
fixtures passed for the earlier source. The changed removal code needs new
source/integration checks; assembled-image and boot validation remain.

Generic-only input selection and identities preserve unchanged next-profile
work. Current Cosign/publication and ZFS-removal changes affect all four profiles, so the
final continuation needs all-profile integration once its source is ready.

## Remaining acceptance sequence

1. Explicit authorized ZFS removal and invariance/ownership regressions pass.
   Confirm one representative changed generic transaction/copy, then
   validate all four profiles because ZFS removal affects both kernel paths.
   Keep earlier standard/DX package evidence as history rather than repeating
   an unchanged probe or treating it as proof of the new source.
2. Inspect one patched local OCI copy with production native scan policy and
   compare all baseline findings, preserving unknowns and not-observed limits.
3. Build both generic images, validate exact kernel/development inventories,
   matching initramfs and supported runtime contracts. Retain the authorized
   virtual-camera removal in user-facing change notes.
4. Require fresh digest-bound image security evidence and isolated signing, then
   Secure Boot/LUKS installation, upgrade and rollback qualification. RPM OpenPGP
   authentication does not prove UEFI or runtime module acceptance.

Source transaction validation passed for the cited revision; latest-source
integration of the new ZFS-removal source is pending. Vulnerability clearance
and release eligibility remain blocked. The Fedora 45 next-kernel stable/testing decision is separate and has
no implemented override. No additional merge or publication is authorized here.

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
ZFS erasure. The new implementation will permit only the additional explicitly
reviewed ZFS names; unrelated erasure remains forbidden. New focused regressions
must prove authorized removal and preservation of all unrelated packages/files.

## Historical source validation and new working source

[Hosted source contracts](https://github.com/closure-labs/finite/actions/runs/38317182847)
passed exact source `4bc79ded4fcf4cfe0d426f9d0bca2f03800b34db`. This is useful
historical evidence; it does not cover the newly authorized ZFS-removal code.
[Draft PR #144](https://github.com/closure-labs/finite/pull/144) targets main.
Its last posted head starts `9a65`; working source is changing and needs new
focused/source contracts, pinned Nix checks, all four image builds and one useful
changed-candidate native scan. Keep the PR draft until those results are bound to
its exact final source. No new-source scan or boot success is claimed yet.

Host ZFS filesystem support is being removed from all four Finite profiles. The
user's separate FreeBSD VM storage setup is an alternative to investigate, not
validated installation guidance and not a replacement for the host root filesystem.
It does not waive desktop security, signing, or boot qualification requirements.
The next 301 testing-update preference remains unapproved; current 300 and the
strict stable-tag policy stay pinned while their October XFS/AMD gap remains open.
