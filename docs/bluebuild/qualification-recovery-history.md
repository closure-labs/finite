# Qualification recovery history

Historical incident and fixture record for earlier profile layouts. Current
requirements are in [workstation qualification](../workstation-qualification.md).
The observations below describe their original runs and revisions.

The September 22, 2026 `finite-dev-next` incident exposed the former shadow-mode
gap: the VM qualification failed at MOK management, but publication proceeded with
`accepted: false`. The image also lacked its replacement kernel's initramfs,
causing encrypted workstations to panic before LUKS unlock. A green historical
workflow alone is therefore insufficient evidence of a successful boot; inspect
the acceptance and promotion records.

`automation/qualification-recovery.json` records an explicit signed predecessor
for an unbootable public digest. It applies only to the named profile while that
exact digest remains published, and always forces qualification. It currently
has no active overrides; the retired Next entries remain retained in the historical record.
The September 22
next-kernel images historically used their signed September 18 predecessors; the DX predecessor
matches the pinned working workstation deployment. Historical signatures do not
constitute VM acceptance: the selected predecessor must boot, upgrade to the new
candidate, and roll back in the current run, alongside a fresh candidate install.

Publication evidence records `publishedDigest` for the image being replaced and
`previousDigest` for the predecessor actually tested, plus `recoveryReason`.
Promotion rejects a changed public digest, altered recovery selection, or missing
matching Secure Boot acceptance. Once a replacement is promoted, the old entry
no longer applies and normal predecessor selection resumes.

Historical predecessor VMs prepare Nix and home SELinux policy once, before the
old image's Nix initialization service. Preparing it at SSH startup was too late:
the old parent substitution made `semanage` reject the nested Nix equivalence,
preventing Nix from starting. Both native policy setup and the historical fixture
now correct home substitutions after policy installation and before adding the
Nix equivalence. Preparation errors remain fatal and retain their original cause.

The predecessor fixture does not repeat this repair after upgrade or rollback.
Its test user also explicitly trusts the approved `valkyrie00/bbrew` tap and sets
the fifteen-minute activation timeout in preserved `customize.nix`; the historical
scaffolds predate those defaults. Fresh candidate VMs receive none of these
compatibility settings and must pass using the image's own setup. Kernel,
initramfs, Secure Boot, signature, upgrade and rollback checks remain unchanged.

The first combined recovery run after these fixes were initially introduced
passed all four fresh-install tests, including both next images on kernel
`7.2.7-300.fc45.x86_64`. Historical predecessor preparation then failed at the
ordering, tap-trust and activation-timeout issues above. No promotion occurred;
fresh VM success alone is not complete upgrade/rollback acceptance.

