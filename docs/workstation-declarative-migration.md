# Workstation declarative migration

The workstation-only helper defaults to a read-only ownership/removal preview:

```sh
python3 scripts/workstation/cleanup-brew.py \
  --historical-policy /path/to/reviewed/historical/brew-packages.json
```

The October 27 pilot preview found 77 installed formulae, 12 inherited Brewfiles
and **zero eligible removals**. Full inventory stays in the private execution
artifacts. All 20 historical policy entries overlap this workstation's stock CLI
bundle. Current installed packages alone cannot establish ownership, and the
workstation's older bundle is not the ownership baseline for the new image.

The helper protects every inherited bundle (including optional bundles), packages
requested by the user, installed dependencies and uncertain provenance. A retained
Finite installer receipt with original before/after inventories is required to
classify an addition as Finite-only. Its policy/machine binding and installed
version metadata must match; its digest is part of the reviewed removal packet.
Without that evidence, an empty removal list is the expected safe outcome.

After the reviewed replacement release is pinned, qualified and actually active,
prepare a reviewed JSON packet containing `schema: 1`, `machineSha256`,
`upstreamBrewfiles`, `ownershipProofSha256` (null without a receipt),
`replacementGeneration` and the exact `removals` array. The first three identities
and bundle map come from the preview; the generation is the active Home Manager
store path. Apply only that packet:

```sh
python3 scripts/workstation/cleanup-brew.py \
  --historical-policy /path/to/reviewed/historical/brew-packages.json \
  --apply --reviewed-removals /path/to/reviewed-removals.json \
  --backup-directory /path/to/new/private-backup
```

Before any removal, the helper backs up the complete profile/configuration tree,
personal modules, locks, relevant shell/Brew configuration, Brew inventory and
active-generation mapping. It checks the active replacement, ownership and
installed dependents again immediately before each exact removal. It uses no
forced uninstall, bundle cleanup or autoremove; automatic Brew autoremove is
disabled for this command. A reviewed empty list still produces a backup.

This is a prepared migration interface and an ownership preview, **not completed
replacement activation**. No application was removed or activated in this pilot.
The Foundation release, immutable Finite pin, both-profile fresh/upgrade/rollback
qualification, workstation replacement activation and final source/security audits
remain open. Stable 0.8.3 preparation and separately approved paired release
publication remain gated on those results. No performance savings are claimed.
