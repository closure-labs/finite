# Bluefin foundations and active Finite variants

The owner selected two active variants: `finite` based on Bluefin, and `finite-dev` based on Bluefin-DX. Both retain the signed, digest-pinned upstream kernel and its modules together. The separate Next kernels and variants are retired; no new Next builds, native scans or VM qualifications are dispatched. Existing published Next releases remain historical artifacts, not maintained update channels.

## Preserve the upstream OS

Finite no longer directly removes ZFS, virtual-camera or other inherited kernel modules, replaces the Bluefin kernel, or prunes its module tree. The upstream kernel and module package inventory and file contents are captured before Finite additions and verified afterward. Only the generated initramfs is rebuilt for Finite's installer and encrypted-root boot requirements; module payload preservation and existing initramfs content checks remain required.

The user's explicit policy trusts the inherited Bluefin ZFS modules as part of the authenticated upstream baseline. Native scans still retain ZFS and other advisory observations, refresh the vulnerability database and evaluate the current policy. This does not hide scanner results or create a general exception for unrelated downstream changes.

Finite retains its installer, Secure Boot and encrypted-root setup, Home Manager and profile personalization, Determinate Nix persistence, SELinux integration, first-login/application migration, authentication additions and branding. Authselect retains the upstream profile and enabled features while adding supported Finite authentication features. The separate Fedora replacement-kernel/IPU7 guarantee and its updater are retired.

## Validation

The change requires fresh hosted builds, native security, signatures and fresh-install plus upgrade/rollback/desktop qualification for the two active variants. Earlier qualifications of replacement-kernel images do not establish this new candidate's eligibility. No local image, ISO, database or VM workload is authorized. Runtime preservation checks establish unchanged upstream kernel/module payloads; they do not independently claim a successful ZFS pool workload.

Reuse timing experiments run only after these OS changes pass fresh hosted qualification. They use the new candidates and receipts as their baseline and cannot independently authorize publication. See [reuse timing experiments](reuse-timing-experiments.md).
