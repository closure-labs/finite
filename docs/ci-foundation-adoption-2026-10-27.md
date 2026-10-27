# Foundation 0.4.0 adoption candidate, October 27 UTC

The reviewed [Foundation v0.4.0 release](https://github.com/closure-labs/foundation/releases/tag/v0.4.0)
is published at `214e62aa594fc51a7416d69a01ab345edf036f77`. Its
[native release workflow](https://github.com/closure-labs/foundation/actions/runs/40452595186)
passed. Both downloaded assets match their API digests and checksum manifest;
the source archive matches the exact reviewed Git archive byte for byte.
Human publication approval preceded publication. Both channel callbacks passed,
and `latest-release` points to that same immutable source.

The [evidence snapshot](ci-foundation-adoption-2026-10-27.json) records the
native source, assets, checksums, updater and input audit. It grants no release
or image publication authority. Finite remains `0.8.3-dev`; previously published
development assets, tags and reservations are preserved.

## Native pin and compatibility

After #292's reviewed main rollout passed, the
[hosted updater](https://github.com/closure-labs/finite/actions/runs/40454988212)
created [#293](https://github.com/closure-labs/finite/pull/293) as immutable bot
user 344936881, `cl-decider[bot]`. Its original commit
`34d4bd23b8601368cfe91cfa6ebb42cab77642c7` is retained in the combined #291 history.
The workflow validated public inputs before issuing its scoped PR token; it
received no publishing PAT.

The three producer files are retained byte for byte: `flake.nix`, `flake.lock`
and `sources/foundation.json`. The pin uses the published revision and
`sha256-xyfDSCECkypjFIhQRmFe0HZuaVzn3Mo6uPVzmw1yQHg=`. A read-only graph comparison
verified every other root input's complete resolved dependency graph, including
follows and cycles, unchanged despite lock-node renumbering. Foundation's added
framework inputs were reviewed separately; no existing upstream locked node was
changed or removed between v0.3.3 and the prepared Foundation release.

Merged #290 resolves public helper executable paths through package metadata,
supporting the old `finite-home-*` and canonical `foundation-home-*` packages.
OS adapters still call the selected Foundation Python helper; configuration is
not reinitialized merely because the OS input changes. Existing personal locks
and customizations remain subject to their preservation checks.

## Qualification and observations still required

The candidate combines this immutable pin with
[bounded Foundation timing collection](ci-foundation-stage-timings.md). Hosted
checks on the prior collector-only head passed; they do not qualify this new pin.
Require the current pinned aggregate and exact-head authority, then both profiles'
protected fresh-install and upgrade/rollback validation and signed main
qualification/promotion. Preserve Secure Boot, encrypted root, enforcing SELinux,
both Nix sockets, actual Home Manager activation and persistence/customization.

No production timing or predecessor miss is claimed yet. Recent main runs
selected no images. The changed VM wrapper and shared timing validator remain
generation inputs, so the first predecessor lookup can legitimately reject an
older context. Retain the resulting fixed diagnostic counters and current-source
path sample; do not weaken reuse identity to obtain a hit.

An upgrade beginning on the old predecessor may initialize with its v0.3.3 helper
and legitimately emit no Foundation timing records. Missing data stays unknown.
Fresh v0.4.0 initialization can supply the new records; nested totals are not
additive, guest timestamps do not establish host critical-path intervals, and
internal Nix evaluation/fetch/build and Flatpak readiness remain unresolved.

The temporary pin PR is superseded by the combined candidate; its duplicate
source validation was cancelled and its spent cost remains part of the native
record. No extra VM round was launched solely to populate this report. Stable
Finite freeze, final security/audit checks, workstation acceptance and the paired
release proposal remain separate requirements in the
[release ledger](v0.8.3-release-plan.md).
