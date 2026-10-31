# Small useful CI results in Cachix

Cachix publication selects the current flake's named `checks` outputs. The
allowlist is evaluated from the checked-out source and locked inputs, recording
each check name, derivation and output path. Outputs do not need a proof label
or cryptographic content: a successful tiny formatting, dependency-lock,
workflow, home evaluation or runtime-contract result is useful because Nix can
reuse its exact derivation result. This policy does not claim FINite caused
recent cache growth.

The current check families are home, nix-lifecycle, bluebuild, vm-iso,
vm-firmware, dependency-updates, dependency-locks, workflows,
repository-security, formatting, home-configurations, flake-input-boundary,
payload-entry and cache-configuration. CI check source changes naturally change
their derivation/output identities. No image payload, scanner, SecretSpec,
interpreter or generic tool root is selected for publication. Read-only
substitution of toolchains remains available.

Before uploading, publication queries the recursive closure of the complete
selection. Every path and reference must be another evaluated current check
output. The union may contain at most **128 distinct store paths** and
**1 MiB of total uncompressed NAR bytes**, counting shared paths once. Per-root
limits alone are insufficient. Missing, duplicate, unreachable, unknown,
malformed or changed metadata fails closed, as do tool references even when
small. These bounds are constants shared by hosted and local publication.

Hosted maintenance retains its existing successful canonical-main workflow
admission and token mapping. Credential-free preparation builds the check
aggregate and verifies every named link against evaluated identities. Its
schema-2 manifest binds source revision, roots, NAR hashes, references, distinct
path count and union bytes. Push checks current identities and the complete
receipt again; the native uploader independently enforces the same policy
before starting devenv. Old tool-root manifests are rejected.

`nix run .#local-cache` retains its successful-check requirement and owned,
mode-0600 handoff. Its final native uploader validates current output identities
and the same union budget. Temporary devenv configuration contains only
validated store roots. No ambient store watcher or post-build upload hook is
introduced. Historical tool-preparation benchmarks remain credential-free
read-only diagnostics; their receipts cannot be used as publication manifests.

Tests use fake metadata and uploader boundaries. They do not access Cachix,
publish artifacts, or establish production boot/upgrade parity. Inventory and
deletion of existing cache contents remain separate and unresolved. This policy
does not change GitHub artifacts, GHCR, production signing or release gates.
