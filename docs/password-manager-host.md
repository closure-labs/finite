# Password-manager host setup

Foundation owns selection, native-messaging manifests and the immutable
`foundation-password-managers.json` generation requirement. Finite supplies the
root-owned `/usr/libexec/finite/password-manager-setup` administrator utility.

Resolve the generation requirement link with `readlink -f` and inspect that canonical
immutable store JSON file before installation. Installation requires literal
approval of the selected package output and both helper and native-wrapper
SHA-256 values. A user-generated requirement never authorizes itself. Each new
version requires a separate privileged invocation; no automatic or passwordless
privilege grant is installed.

The utility validates immutable source paths and content, copies only the pinned
native security wrapper, uses root ownership with group `onepassword` and mode
`2755`, and retains GC roots for the package and wrapper closures. It does not
execute user setup scripts, assign users to the helper group, use setuid, or
replace the Nix store binary's permissions. SELinux labeling remains enforced.

The group GID must be greater than 1000, as required by 1Password. New groups use
ordinary `groupadd`; existing groups with GIDs at or below 1000 require an
explicit administrator correction. Installation and status reject invalid GIDs,
including otherwise matching existing installations. After changing a group's
GID, correct the installed wrapper's group and restore mode `2755`, then restart
the desktop app and browser. Do not add the user to this identity group.

Review status after installation. Preserve prior helper versions and their
closure roots for Home Manager rollback; removal refuses to invalidate retained
generation references. A package or wrapper hash mismatch is a failure, never a
reason to relax validation or install a different executable.

The administrator utility is intentionally narrow. It is not a general service
or command-elevation API. Browser integration still requires an actual connection
test with the desktop app and the intended browser extension.

Run removal only while Home Manager operations are quiescent; concurrent
activation/removal is not supported.
