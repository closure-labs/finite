# Native bootc runtime

`sources/bootc-runtime.json` selects the upstream runtime shared by both native
recipes and the disposable native installer. The temporary source is the merge
of [upstream PR #2573](https://github.com/bootc-dev/bootc/pull/2573), which adds
VFAT XBOOTLDR support. It carries no downstream Rust patch. Its declared version
is still 1.17.4; calling this snapshot 1.17.5 would misidentify the source.

`scripts/bluebuild/stage.sh` stages a native Fedora bootc RPM before image
construction. The builder verifies the source archive checksum, uses Cargo's
locked dependencies, compiles with one job, and caps its container at 2 GiB.
`install-native-bootc.sh` checks the staged payload, applies the RPM with local
dependency checks, and records executable hashes before initramfs generation.
The installer must run this same runtime before invoking native installation;
updating only the installed image cannot fix an older installer binary.

For isolated local builds:

```sh
python3 scripts/bluebuild/stage-bootc-runtime.py --engine podman \
  --output artifacts/bootc-runtime-build/packages
```

`FINITE_PODMAN_ROOT` and `FINITE_PODMAN_RUNROOT` optionally select separate
Podman storage. Reuse requires matching source, build inputs and RPM bytes.
Use a fresh output directory after changing the pin or builder. The RPM's low
release number allows a later official distro RPM to supersede it.

The daily `update-bootc-runtime.yml` workflow proposes an official release at
least 1.17.5, including later minor releases. It rejects drafts/prereleases,
resolves the tag's commit, verifies that the required fix is an ancestor, and
checks the source archive's declared version before recording its checksum.
The resulting PR uses an official version tag and normal protected checks.
The recorded commit and archive checksum still identify the reviewed bytes.
Run `python3 scripts/ci/update-bootc-runtime.py` to perform the same selection
locally. No future release version is synthesized while 1.17.4 remains latest.

The separately locked 1.17.1 canonical OCI importer is an integrity tool, not
the installer or installed OS runtime. Its version does not select bootloader
placement. The existing OSTree Anaconda ISO pipeline also remains distinct;
this runtime integration does not turn its kickstart into native installation
media. Workstation coexistence and migration are the next design phase.
