# Installer squashfs stage override

Image Builder v79 hardcodes `zstd` for `bootc-generic-iso`, but does not pass a
compression level. Squashfs-tools 4.6.1 consequently uses Zstd level 15. The
same Image Builder version has no CLI, Blueprint, distro-definition, or
`iso.yaml` option for changing that level.

Finite mounts `org.osbuild.squashfs` over the pinned builder's stage only
during ISO construction. The override preserves the upstream stage and adds
`-Xcompression-level 1` when the manifest requests Zstd without an explicit
level. It does not change the compressor, the installed Finite payload, or
the installer boot contract.

`lock.json` ties the override to the Image Builder digest and to checksums of
both the override and the upstream stage it replaces. An Image Builder update
must review and refresh the override instead of silently carrying it across an
internal API change. Remove this directory and its mounts after Image Builder
exposes a supported Zstd-level setting.

## Benchmark

The benchmark used the Fedora 44 installer environment produced by
`installer/Containerfile`, squashfs-tools 4.6.1, eight processors, identical
exclusions, and a 3,580,319.93 KiB source tree:

| Method | Time | Filesystem size | Relative to Zstd 15 |
| --- | ---: | ---: | ---: |
| Zstd level 15 (upstream default) | 52 s | 1,730.10 MiB | baseline |
| Zstd level 1 | 8 s | 1,918.35 MiB | 6.5x faster, 10.9% larger |
| Zstd level 3 | 17 s | 1,870.92 MiB | 3.1x faster, 8.1% larger |
| LZ4 | 7 s | 2,217.84 MiB | 7.4x faster, 28.2% larger |

Zstd level 1 dominates LZ4 for this workload: one additional second saves
about 299.5 MiB. The successful hosted-run baseline spent 401.41 seconds of a
1,554-second installer action in squashfs compression, producing a 3,884.45
MiB filesystem from 10,523,859.67 KiB.
