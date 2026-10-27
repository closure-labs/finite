# Foundation 0.4.1 adoption candidate, October 27 UTC

The published [Foundation v0.4.1 release](https://github.com/closure-labs/foundation/releases/tag/v0.4.1)
is pinned at `8ae2b6bdcca1f7c025fd9c75e7b5273cffd79de0`. Its
[native release workflow](https://github.com/closure-labs/foundation/actions/runs/40461006918)
passed. Both downloaded assets match their API sizes, digests and checksum manifest.
This patch adds guarded Intel IPU7 camera diagnosis/repair and refreshes Foundation's
Den, Home Manager, Determinate Nix, Nixpkgs and flake-parts dependency locks.
Foundation's `scripts/home.py` initializer is unchanged from v0.4.0; the opt-in
stage timing producer remains compatible with this collector.

The [evidence snapshot](ci-foundation-adoption-2026-10-27.json) records the
native source, assets, checksums, updater and input audit. The earlier v0.4.0
publication and pin evidence remain under `priorCandidate`; those historical
publication approval and exact-source-archive observations apply to v0.4.0 only.
The snapshot grants no release or image publication authority. Finite remains
`0.8.3-dev`; previously published development assets, tags and reservations are preserved.

## Native pin and compatibility

After #292's reviewed main rollout passed, the
[hosted updater](https://github.com/closure-labs/finite/actions/runs/40462552121)
created [#295](https://github.com/closure-labs/finite/pull/295) as immutable bot
user 344936881, `cl-decider[bot]`. Its original commit
`538c36b598ab693436bce1243b393ff1de499173` is retained in the combined #291 history,
alongside the earlier v0.4.0 pin. The workflow validated public inputs before
issuing its scoped PR token; it received no publishing PAT.

The three producer files are retained byte for byte: `flake.nix`, `flake.lock`
and `sources/foundation.json`. The pin uses the published revision and
`sha256-c1Opu2UmbVqhcE52rx6/RZVGYiSHfrEeNin6IqAMXmM=`. A read-only graph comparison
verified every other Finite root input's complete resolved dependency graph,
including follows and cycles, unchanged despite lock-node renumbering. Foundation's
own transitive dependency updates are part of this adoption and require the
current hosted aggregate and both profiles' qualification.

Merged #290 resolves public helper executable paths through package metadata,
supporting the old `finite-home-*` and canonical `foundation-home-*` packages.
OS adapters still call the selected Foundation Python helper; configuration is
not reinitialized merely because the OS input changes. Existing personal locks
and customizations remain subject to their preservation checks.

## Qualification and observations still required

The candidate combines this immutable pin with
[bounded Foundation timing collection](ci-foundation-stage-timings.md). Hosted
checks on the prior v0.4.0 candidate passed; they do not qualify this v0.4.1 pin.
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
Fresh v0.4.1 initialization can supply the new records; nested totals are not
additive, guest timestamps do not establish host critical-path intervals, and
internal Nix evaluation/fetch/build and Flatpak readiness remain unresolved.

The temporary pin PR is superseded by the combined candidate; its duplicate
source validation was cancelled and its spent cost remains part of the native
record. No extra VM round was launched solely to populate this report. Stable
Finite freeze, final security/audit checks, workstation acceptance and the paired
release proposal remain separate requirements in the
[release ledger](v0.8.3-release-plan.md).
