# Workstation reboot remediation

User-approved scope: Foundation and Finite source fixes plus workstation cleanup.
Use the Nix and great-cto workflow. Preserve schema 3 selections, OpenCode, personal
inputs/stateVersion, Espanso pins, data and rollback generations. Retire Claude
integration without installing Claude. Keep Nix 1Password and add provider-aware
browser integration with explicit administrator approval of each native helper.

| Work | Owner | Dependency / acceptance |
|---|---|---|
| Immutable source resolution + no-upgrade preparation | Foundation | Exact-source/CI/hash tests and failure leaves live tree unchanged |
| Automatic password-manager aspect | Foundation | GUI/wrapped/absent/ambiguous tests; immutable artifact hashes; actual build |
| Narrow manual helper install | Finite | Exact approvals, root:setgid-only mode, source validation, GC roots, rollback/security review |
| Updater dispatch and image repairs | Finite | Prefer installed command, guarded extension schemas, identity-checked camera migration |
| Personal cleanup | User consumer | Native Gear Lever, retire only Claude association, backups and successful activation |
| Adoption and closure | Coordinator/operator | Qualified source/image, root approval, fresh browser handshake, physical camera, reboot |

PR #307 already implements main-delivery proposals; reuse it. The legacy OS shim
exists but runs its bundled source, so correct dispatch rather than assume a
missing command. QA is a baseline; mark each subsequent receipt passed/failed/
not_run/inconclusive. Keep camera override until the new image has direct-format,
capture, WebRTC, suspend/resume and reboot evidence. Keep the temporary personal
Brew wrapper until corrected Foundation is adopted. Bitwarden's write attempt
is a minor ownership warning; do not overwrite its mutable application settings.

Administrator approval binds the literal package and native helper/wrapper hashes;
no user-generated requirement approves itself. Never install setuid wrappers,
passwordless sudo/polkit rules, automatic privilege refresh or user memberships.
No merge, image deployment or physical acceptance can be inferred from source
fixtures or a successful Home Manager build.
