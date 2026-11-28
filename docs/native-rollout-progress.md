# Native rollout continuation — 2026-11-25

The plan selects separate native tags and an operator-run parallel workstation
migration. Both native ISO profiles passed hosted fresh-install and encrypted
first-boot qualification using disposable signing keys. `VERSION` is still
`0.8.3-dev`. [Operator-approved rollout plan](plans/PLAN-native-systemd-boot-rollout.md)

## History and preserved work

- Read native jj changes `mtvzotoy` and `znvxoqxs`, installer prototypes
  `pyvvsonm` and `pqvtovuo`, installer research `zlxnkvqm`, and Doppler retirement
  `prmlluum` before modifying the stack.
- GitHub [PR #425](https://github.com/closure-labs/finite/pull/425) merged as
  `bcc3eeeb05fe04c7871386214e56d1de6c3aaf5a`. Fetching main also brought in
  #426; the rebase destination is `19507b726c72`. Rebased `mtvzotoy` and its
  installer descendants from their old `55d935cc` base. Stable jj change IDs
  survive this operation; old commit hashes do not name the updated stack.
- Kept the shared review-token/admission actions, experiment/evidence archives,
  inline protected boot-signing disk cleanup and 08:47 UTC bootc updater cron.
  Conflict resolution retains the bounded `single_archive_reader`, native seal
  evidence, current action-pin contracts and shared-payload exclusions.
- The unrelated secret-history edits in `vquwtynx` remain on their original
  parent. Three pre-existing bookmark conflicts were left alone.
- `prmlluum` / `doppler-removal` already records deletion of the GitHub pilot
  environment and allowlist entry, plus source-policy retirement. Do not repeat
  those deletions or provision Doppler. That independent change is not an
  ancestor of this stack at this checkpoint. Its merge/live audit still needs
  reconciliation; this continuation did not recheck or delete organization
  credentials or any Doppler-side identity.
- The Anaconda investigation led to the custom installer path implemented by
  the prototypes. [Installer research](native-installer-research.md)

## Current changes

| Stable jj change | Result | Remaining boundary |
| --- | --- | --- |
| `mtvzotoy`, descendants | Native boot stack rebased onto current main; all five payload inputs and `FINITE_CI_VARS` forwarded | Production-key full-profile qualification remains open |
| `znumxztt` | Separate native recipes, metadata/update channels, build/identity support and native-only runtime staging | Automatic native publication remains closed |
| `xnkqwxpk` | Native media identity checks, disk revalidation, live kernel/scratch fixes and offline EFI transaction | Account creation and interrupted-install cleanup remain open |
| `umpkpluv` | Both native ISOs pass capped fresh-install and encrypted first-boot checks over read-only VirtIO media | Production-key qualification, upgrades and rollback remain open |
| `xtqwuvkl` | This handoff, approved plan and retained research | Update this record with subsequent exact artifacts/results |

The registry layout is:

| Profiles | Tags in `ghcr.io/closure-labs/finite` | Boot architecture |
| --- | --- | --- |
| `finite`, `finite-dev` | `finite`, `latest`, `finite-dev` | Existing OSTree / inherited bootupd / Anaconda |
| `finite-native`, `finite-native-dev` | `finite-native`, `finite-native-dev` | Composefs / shim / signed systemd-boot / signed UKI |

Default recipes and `shared/base.yml` match main's OSTree shape. The native
recipes alone select `shared/native-root.yml` and enable the EFI updater.
Bootc source refresh updates all four recipes together against the same two
verified Bluefin bases. Native runtime RPM compilation is skipped for OSTree.
Root build artifacts use `root-image-*` only for native signing; default
publication retains `image-*`. Setup actions declare the current workload roles.

`publication.yml` routes the qualified OSTree pair through `image.yml`.
`native-production-validation.yml` passes same-run payload identities to
`image.yml` and seals the resulting digest in its protected `seal` job. This
workflow writes an isolated candidate tag for qualification.
`publication.py promote` explicitly rejects the native profiles until dedicated
native acceptance exists. Do not remove that guard just to get a green run.

The [installer operator guide](../scripts/native-installer/README.md) describes
the prototype and its gaps. It now targets the correct native tags, verifies the
embedded digest/profile and bootc bytes before disk discovery, excludes active
block-device holders, and revalidates the selected stable ID just before wiping.
It restores the live kernel from `/kernel`, makes target-disk scratch a mount
boundary for bootc's empty-root check, mounts the installed deployment, and uses
its signed EFI payload/certificate and persistent journal. Runtime EFI guards
still reject OSTree and non-strict composefs boots. All test installs used
disposable qcow2 disks on hosted runners.

The installer fixes use the exact runtime source, not an assumed CLI:
[bootc mount API at the pin](https://github.com/bootc-dev/bootc/blob/8275daa9227f7c4ee893c0b05b4134dc2ff11283/crates/lib/src/mount.rs),
[empty-root checks at the pin](https://github.com/bootc-dev/bootc/blob/8275daa9227f7c4ee893c0b05b4134dc2ff11283/crates/lib/src/install.rs),
and [image-builder v91.0.0 ISO contract](https://github.com/osbuild/image-builder/blob/v91.0.0/doc/20-advanced/20-bootc/10-isos.md).

## Local source verification

Pinned checks used the current root lock through the lightweight local helper
`artifacts/native-checks.nix`: `nice -n 19`, Nix `--max-jobs 1 --cores 2`, and a
watchdog that stops the command if available host memory drops below 3 GiB.
These are contract/lint builds, not OS-image builds. No VM was started.

- `bluebuild`: **116 suites, 2,052 cases passed**, including 23 installer and
  seven EFI cases. Preserve the suite's explicit skips; this is not a claim
  that environment-dependent tests or actual guests ran.
- `workflows`: **two suites, 15 cases passed**, including workflow contracts, actionlint, offline Zizmor
  and shellcheck. No unreviewed allowlist or credential changes were needed.
- Alejandra accepted the changed Nix source declarations; `git diff --check`
  passed. Documentation checks run on a tracked-file export, excluding ignored
  container storage under `artifacts/`.
- BlueBuild 0.9.37 passed live schema validation for both native recipes after
  retrying access to the schema endpoint. The pinned base signatures also
  verified with the corresponding Bluefin project keys.

## Hosted native ISO qualification

The workstation had approximately 27 GiB of free storage and 4.3 GiB of
available memory at preflight. The requested 3 GiB guest plus 3 GiB host
reserve needs a different host. The upstream repository's disposable
`qualification/native-iso` branch builds one full profile at a time and
runs one VM, with two vCPUs and 3 GiB RAM. It boots the built ISO under
Secure Boot OVMF, supplies the ordinary installer prompts over serial, and
reboots the newly installed qcow2. The workflow artifacts contain the media
and guest identities. [Passing run](https://github.com/closure-labs/finite/actions/runs/45823572183)

The validation image uses the full native recipe plus a VM-only serial
console and observation unit. The runner creates a disposable signing key
and pre-enrolls its public certificate and the package's module certificate
in the guest firmware file. The receipt requires enforcing SELinux,
lockdown, LUKS-backed sysroot, strict composefs verity, shim, XBOOTLDR
placement and signed ZFS and v4l2loopback loads. This scope covers fresh
installation and the first encrypted boot. Interactive MOK enrollment,
recovery key and FIDO2 unlock, upgrades, rollback and desktop login require
their own observed results.

Both native recipes passed BlueBuild 0.9.37's live schema validation after
retrying with network access. The corrected source passed the pinned
bluebuild group with 116 suites and 2,054 cases and the workflow group
with two suites and 15 cases. The first hosted run `45701591964` was
superseded to include the VM test. The next run `45702162585` passed
toolchain setup and KVM access, then began compiling an importer using the
rebased root Nixpkgs version. The rebased importer had a different Nix
output path from the approved binary. The replacement run uses the pinned
Nixpkgs revision `26f4107e`, which locally resolved to the reviewed
bootc 1.17.1 binary SHA256
`f26b09f987697c1755a3d65d6b45e31534e59cdd6ffee6c664a35b66acc20f0a`.

Run [45703547295](https://github.com/closure-labs/finite/actions/runs/45703547295)
built the right importer derivation and stopped at the executable check
before staging the ISO images. That job emitted neither its computed hash
nor an ISO receipt. Change `kylntukl` emits the version and hash and lets the
dedicated disposable branch bind its same-run Nix-built executable to the
seal and verification receipts. Production consumers still require the
reviewed executable hashes and reject validation receipts.

Run [45705616551](https://github.com/closure-labs/finite/actions/runs/45705616551)
confirmed `bootc 1.17.1` at the pinned store output and reported executable
SHA256 `9e8d8d74be1237fcec3fdd10716526aae4660293c7f67ac23560077fa56f72f6`.
The different local and hosted executable hashes were observed at the same Nix
output path. The run then failed in upstream verification with
`ModuleNotFoundError: No module named 'yaml'`. Change `plllnsxt` keeps the
pinned VM Python with PyYAML on the host PATH and limits the plain Python
in the sealing tools to the seal subprocess. It preserves setup-nix's cache
configuration and stages the image before compiling the importer.

Run [45707478815](https://github.com/closure-labs/finite/actions/runs/45707478815)
got through the pinned Python environment, upstream signature checks and
recipe validation. Docker failed before packaging the RPM because the helper
stages a `Containerfile` and Docker searches for `Dockerfile` by default.
Change `kwzzqnqt` selects the staged file explicitly for Docker and Podman.
Change `xxowoprp` checks the engine invocation, the staged file and the RPM
receipt in the existing source tests. The pinned bluebuild and workflow groups
passed with 2,055 and 15 cases, respectively. The next run entered the locked
runtime RPM compile for `finite-native`; both ISO checks remain pending.

Change `knurtqry` also validates the native recipe identities and pins before
authenticating the two exact Bluefin manifests, using an opt-in mode on the
shared verifier. The next pinned check passed 116 bluebuild suites and 2,056
cases plus two workflow suites and 15 cases.

Run [45707828686](https://github.com/closure-labs/finite/actions/runs/45707828686)
completed the stable bootc RPM build and common Nix payload, then reached
layer 42 of the `finite-native` BlueBuild. The Fedora 44 bootstrap RPM
required OpenSSL 3 sonames that the Fedora 45 root lacked. Registry metadata
for both locked Bluefin roots shows `45.20261124`. Change `psqwwmnk` pins
Fedora's `amd64` Fedora 45 manifest at
`sha256:89fe812033e4b10bb8b05bd573fce914e7a11c2337772ede441c9382f874717b`
and checks the Fedora release in both builder and destination before accepting
the RPM. The upstream source archive remains pinned to the same revision and
checksum. Its locked `openssl-sys` 0.9.118 supports OpenSSL 4.
[Fedora 45 package](https://packages.fedoraproject.org/pkgs/openssl/openssl-libs/fedora-45.html)
[Rust OpenSSL upstream release history](https://github.com/rust-openssl/rust-openssl/releases)
Run [45713686563](https://github.com/closure-labs/finite/actions/runs/45713686563)
produced the Fedora 45 RPM with OpenSSL 4 dependencies and rebuilt the shared
Nix payload. RPM resolved the package dependencies and reached transaction
preparation, then rejected the unsigned local artifact. Change `kqoxwtrt`
applies RPM's digest verification mode for that one offline transaction
after the exact file hash and Fedora major checks.
[RPM verification modes](https://rpm.org/docs/6.0.x/man/rpm-config.5)

The retry at `dbebf626` configures the one-job, two-core Nix cap from
setup, wraps VM tool realization in the memory watchdog, and reserves the live
validation serial port for the installer. The capped local full check stopped
at the 3 GiB reserve. Seven runtime cases, 24 installer cases, six resource
cases, actionlint, Zizmor and shellcheck passed in targeted checks. Run
[45718895044](https://github.com/closure-labs/finite/actions/runs/45718895044)
entered the RPM compile and was superseded by the shared-runner retry.

Run [45719595387](https://github.com/closure-labs/finite/actions/runs/45719595387)
used `b41f00b9`. Changes in `tqxumrys` keep both profiles on
one ephemeral host to reuse the checked runtime RPM, shared Nix payload
and pinned importer. Profile steps and VMs are serial. Each profile gets
fresh installation media, a fresh target disk, an independent seal and
its own checksums and guest transcript. A profile failure fails the overall
job. The runner applied one Nix job with two build and evaluation cores.
The stable build passed the corrected RPM transaction and the native initramfs
step. The dev build reused the checked RPM and common payload within four
seconds of the stable step finishing. Both full roots and their VM observation
images built. The latter Docker image IDs were:

- `finite-native`: `sha256:0d1082e0fce87a63f3791b449f9461a07eb652b5df4d9d602ea06c7e9ad82072`
- `finite-native-dev`: `sha256:35a1043e77e8758e823c6c4fcb31a4d8a882d74bb5d7abd7f186ef9091fc044f`

Both then stopped before applying the seal because `docker create` requires a
command when the image supplies no default. Change `ktlkzqpw` gives the
copy-only container an explicit placeholder and cleans it up on failure.

Run [45725401794](https://github.com/closure-labs/finite/actions/runs/45725401794)
at `24f80502` copied the certificate and independently imported and verified the
full stable native root. Artifact `15078600898` retains the validation-only seal
with archive SHA-256
`d3e0b828067eb37b719a78808863e8c27eafdbed324b7f11c7f678350b8af7d6` and strict
composefs bootable root
`f8bdad78ed8ca78818bd19f4a409f7ea01a814650cbdc41a725dd00b2086f49450445198b390b414908802f7795d36fb8c526ea8a4707b8442dafae4b62c261a`.
The runner started with 88 GiB free and skipped cleanup at the old threshold.
During osbuild's embedded payload copy it had 26 MiB left and the write failed
with `ENOSPC`. The dev archive then hit `ENOSPC` in the canonical bootc import.

The retry at `16d4599a` increases the runner cleanup threshold, drops
both Docker build caches after OCI export, releases the sealed archive after
matching Podman import, and removes the per-build osbuild cache at exit. It
also removes the two assembly-only Podman images after ISO checksum verification
and before allocating the QEMU guest disk. Free space is logged before sealing,
osbuild and QEMU.

Run [45735032665](https://github.com/closure-labs/finite/actions/runs/45735032665)
successfully assembled and checksum-verified both native ISOs. Both sets of
installation records and strict native seal records are retained in
[artifact 15088485817](https://github.com/closure-labs/finite/actions/runs/45735032665/artifacts/15088485817).
Their validation-only ISO SHA-256 values are:

- `finite-native`: `2f0b3a05c6d5d8ef4c37750163fd7548946de7484e6bb09cafb4d2c19f8f60fa`
- `finite-native-dev`: `886722533d164c6625206b7b727f2d486b482c37283f389451a92b4d7cf970fc`

Both guests reached the installer under UEFI and stopped before disk selection.
Stable began the embedded-payload error. The original offline transport copied
the image into a second `containers-storage` instance during ISO assembly,
where the original manifest digest could change. The serial collector killed
each guest on the error prefix and cut off the rest of the diagnostic.

Run [45757338767](https://github.com/closure-labs/finite/actions/runs/45757338767)
at `964750b5` embedded the authenticated OCI layout directly and verified the
original manifest SHA-256 during media build and live preflight. The stable
ISO SHA-256 is `1621dd4d26a4983b5833c605e32144a6fafa4cf017d55261b2258c9229bca94b`.
Its strict seal and full serial transcript are in
[artifact 15092065583](https://github.com/closure-labs/finite/actions/runs/45757338767/artifacts/15092065583).
The Secure Boot guest partitioned the disposable disk, set up LUKS2 and ext4
verity, and bootc imported all 100 layers and installed systemd-boot. The
installer then stopped at `Remove scratch space` with `Read-only file system`.
The new retry superseded the dev step before it produced its ISO.

Change `qlqpwwmt` keeps the locked bootc filesystem finalization. It reopens only
the encrypted backing filesystem for scratch removal and persistent EFI setup,
then returns it to read-only after the offline deployment is detached. The
composefs deployment root and finalized XBOOTLDR stay read-only. All 54
targeted native tests passed. Run
[45766034663](https://github.com/closure-labs/finite/actions/runs/45766034663)
tests both profiles at `015dbf25` with the correction. In attempt 1, both failed
before building media when the fixed-output Nix fetch of Determinate Nix
Installer `v3.24.2` returned HTTP 403. The exact release URL subsequently returned
HTTP 200 and its 78,449,072 bytes matched the locked SHA-256
`22ed14ee1b24d100d388f1fc245e3062bd5982433d159cffa6dec34c0eb15dab`.
[Attempt 2](https://github.com/closure-labs/finite/actions/runs/45766034663/attempts/2)
reran the same revision and passed the dependency fetch. The stable ISO SHA-256 is
`4298e643bf8f65b6de6570d96cb92709708e79e8e45faf0af67bc59fe22162bc`.
[Artifact 15097714623](https://github.com/closure-labs/finite/actions/runs/45766034663/artifacts/15097714623)
shows the guest passing scratch cleanup, verifying XBOOTLDR placement, mounting
the installed deployment and writing the fallback shim configuration. Step 23
failed with `Permission denied: '/usr/libexec/finite/update-efi'`. The image ships
that Python source at mode `0644`, and its systemd service runs it with Python.

Change `suvxmqsp` gives the offline installer the same `/usr/bin/python3`
command prefix and keeps its explicit deployment, ESP and recovery-journal
arguments. All 54 targeted cases passed, including the service invocation
contract.

Run [45782220573](https://github.com/closure-labs/finite/actions/runs/45782220573)
at `359a1ca0` completed the stable installation and committed the EFI update.
The stable ISO SHA-256 was
`32a8e09e0314b44dde7455f3d6ac3619ca6f5dbcd406f43ca79d228d4bd98984`.
[Artifact 15108695380](https://github.com/closure-labs/finite/actions/runs/45782220573/artifacts/15108695380)
shows the installed guest unlocking LUKS2 and reaching the login prompt. The
runtime EFI updater and first-boot observer failed when `/efi` was absent from
the installed mount table. The serial log also shows `mokutil --test-key`
reporting both keys as enrolled while the installer treated its exit status
as missing enrollment.

Changes `nwpztnro`, `qsvsqtpz` and `mkxnzlmu` persist `/efi` and `/boot` by the
installed GPT partition UUIDs, match exported MOK certificates by DER bytes,
and require a successful runtime EFI update in the fresh-boot receipt. A
first-boot failure now prints a complete capture marker and the EFI journal
tail when applicable. All 59 targeted native and MOK tests passed. Run
[45803664314](https://github.com/closure-labs/finite/actions/runs/45803664314)
tests both profiles at `c78451f8`. `finite-native` built, checksum-verified its
ISO, completed the offline install and passed the first encrypted boot in one
two-vCPU, 3 GiB guest with a 3 GiB runner reserve. Its exact ISO SHA-256 is
`3a605a195a43b2d001b977064d25381ad260a813ec3ba3ec0cad382ecbe978a5`.
[Artifact 15115561134](https://github.com/closure-labs/finite/actions/runs/45803664314/artifacts/15115561134)
holds the passing `fresh-acceptance.json`, checksum inventory, seal and both
transcripts. The receipt matches the strict composefs root and signing
certificate and confirms Secure Boot, enforcing SELinux, LUKS2-backed sysroot,
the runtime EFI refresh, both boot partitions and signed ZFS and v4l2loopback.
The same run built and verified the `finite-native-dev` ISO with SHA-256
`863ce327a6c8591b1dee5aad3026cb6d0e727f3c40a9ea1347debc7cf02a3780`.
[Artifact 15118830878](https://github.com/closure-labs/finite/actions/runs/45803664314/artifacts/15118830878)
contains its strict seal and installer startup log. OVMF launched the SATA
DVD's shim, which returned `Device Error` reading `\EFI\BOOT\grubx64.efi`.
The guest exited before reaching Linux or selecting a disk. The dev live tree
compressed to 11,981.45 MiB, up from 6,117.63 MiB in the previous dev ISO that
reached installer preflight. The size difference is observed. The reason for
the firmware read error remains undetermined.

Change `umpkpluv` attaches the exact ISO as a read-only VirtIO disk and boots
its existing GPT EFI System Partition. The first boot of the installed system
has only the disposable target disk attached. The run retains both the GPT and
the El Torito layout and records the tested boot transport in each receipt.
All 60 targeted source checks passed. Both profiles built and passed the capped
VM checks in run `45823572183`, attempt 1, job `139921807416`, at source revision
`9275f951d92e0937126eaf83e481830cad5ca02f`. [Passing job](https://github.com/closure-labs/finite/actions/runs/45823572183/job/139921807416)

| Profile | ISO SHA-256 | Evidence |
| --- | --- | --- |
| `finite-native` | `0148449ac7bce1a41e8d39c14d5402094a10df17dbb29b3ef63b627b3c74e915` | [Artifact 15130110133](https://github.com/closure-labs/finite/actions/runs/45823572183/artifacts/15130110133) |
| `finite-native-dev` | `2ef7115f2c17380f92c8214cc976911f98133de93deb2cb72647e95514cf73bf` | [Artifact 15136253627](https://github.com/closure-labs/finite/actions/runs/45823572183/artifacts/15136253627) |

The runner verified both ISO files against their inventories. Each retained
`fresh-acceptance.json` matches the checksum inventory, source revision, sealed
OCI manifest, strict composefs root digest, public certificate and first-boot
serial facts. Both guests reported Secure Boot, enforcing SELinux, LUKS2-backed
sysroot, a successful EFI updater, a 600 MiB ESP and a 4 GiB XBOOTLDR, and loaded
signed ZFS and v4l2loopback modules. The guests ran sequentially with two vCPUs,
3 GiB RAM and a 3 GiB runner reserve. The installer and first-boot transcripts,
runtime receipts, validation seals and GPT and El Torito layouts are retained
alongside the acceptance receipts. The earlier optical dev failure remains
open. The passing dev receipt covers hybrid disk boot.

A capped re-seal of a historical Fedora fixture with the proper explicit
`rw` argument passed independent OCI import and UKI verification. Its
bootable root matched
`9c13a50e83b3452c669bc42671031205697b6bb741d025d9ba33ced6f297826d467b8d500e78fc084282f64dfe507f8b65d3b5f6f032d6410efba2a4e51bc0bd`.
The local fixture demonstrates the importer and sealer cleanup changes. The
hosted job above provides the full-profile fresh-install evidence.

## Hosted upgrades and rollback

Change `uvttrxyp` adds the sequential capped lifecycle jobs. The fixtures
pair the stable kernel `7.2.11-300.fc45.x86_64` with the pinned Fedora 45
loader `262-3.fc45` and a full update image using kernel
`7.3.4-300.fc45.x86_64` and loader `262.1-1.fc45`. The update uses the
authenticated Bluefin and Bluefin DX manifests recorded in
`sources/native-lifecycle-fixture.json`. Each guest imports its update
through `bootc switch` from a read-only VirtIO OCI archive. Five boots
cover staging, the new root, the new running EFI loader, the restored
root and the restored running loader. Receipts require matching signed
root and EFI identities, Secure Boot, SELinux, signed modules and
persistent `/etc` and `/var` state.
[Fedora baseline package](https://packages.fedoraproject.org/pkgs/systemd/systemd-boot-unsigned/fedora-45.html)

The stable job in run `45863337122` built both roots and an ISO with
SHA-256 `4ceb61304c0cfef3b28956d019c57ec433eb003195bbe47720b8c539b858d212`.
The guest installed, booted the older kernel and loader, and staged the
sealed update. The host stopped at a nested brace in a partial serial
read, before an upgraded boot. Change `lrnxlqly` requires complete JSON
lines and frames the full bootc status as numbered 256-byte chunks.
Run `45877540862` recovered all seven transition chunks. The staged
root digest matched the independently verified candidate and the audit
log recorded successful finalization before poweroff. The console
appended a kernel message directly to the preceding boot receipt, so
the host did not reopen the disk for the upgraded boot. Change
`wzokysmv` adds numbered Base64 frames with explicit terminators for
the boot, transition and shutdown receipts. Run `45889758659` passed
serial framing and booted the sealed stable-profile update with kernel
`7.3.4-300.fc45.x86_64`, Secure Boot, enforcing SELinux and a successful
EFI refresh. The guest stopped because the upstream image shipped no
ZFS module for that kernel.
[Stable failure evidence](https://github.com/closure-labs/finite/actions/runs/45863337122/artifacts/15143609769)
[Second stable artifact](https://github.com/closure-labs/finite/actions/runs/45877540862/artifacts/15151330081)
[Updated boot artifact](https://github.com/closure-labs/finite/actions/runs/45889758659/artifacts/15157849042)

The ZFS check follows the upstream module inventory. Both signed
update bases ship v4l2loopback and omit ZFS. The guest requires signed
v4l2loopback on every boot and verifies signed ZFS loading whenever
the installed kernel provides it. Changes `yuryrtnm` and `sknktsuv`
build the common Nix payload and locked bootc RPM once in parallel
producer jobs. Then stable and development qualify on separate hosted
runners, each with the original guest and memory caps. Run
`45907617967` finished its shared Nix payload in 21m54s while the
11m24s RPM build ran concurrently. The profile jobs started one
second apart. Stable took 60m27s on its runner and passed 82m24s
after the producers started. The previous serialized stable job
took 146m04s and stopped on the unavailable ZFS module before
rollback, so these measurements cover different endpoints.
[Parallel lifecycle run](https://github.com/closure-labs/finite/actions/runs/45907617967)

Stable booted the new sealed root, verified the running new EFI
loader, rolled back, and verified the original root and loader
with both persistence sentinels present. The ISO SHA-256 is
`16e83ec11ff92f9444f1fc7dfdd8a0fd7d3d3cb85a9385d87e3053bfe91bc2a2`.
Each receipt proves Secure Boot, enforcing SELinux, encrypted
root, prerequisite signed modules and successful EFI refresh.
[Stable lifecycle evidence](https://github.com/closure-labs/finite/actions/runs/45907617967/artifacts/15162017874)

Development built and booted ISO SHA-256
`da9484f25e54075cc3b81dfb9fa30d0ecc77a881cf9c613d0606a42fb79f9723`,
staged the verified candidate and finalized it on shutdown. A
kernel EXT4 message interrupted the third baseline receipt chunk
inside its Base64 payload. The host stopped before the updated
boot. Change `uornztuk` puts complete, bounded JSON lines on a named
VirtIO evidence port and keeps the UART for prompts and diagnosis.
Run `45918999917` exercises the independent transport for both
profiles under the same caps.
[Development serial evidence](https://github.com/closure-labs/finite/actions/runs/45907617967/artifacts/15163276195)
[Dedicated evidence channel run](https://github.com/closure-labs/finite/actions/runs/45918999917)

Both profiles passed the dedicated-channel run at source revision
`74b8e04082ae1d3750026c01e74b4aa2be7ddb05`. Their jobs started at the
same second and finished in 90m17s and 90m29s. The whole workflow
finished in 112m22s. Each guest installed from its hybrid ISO and
verified five separate boots, including kernel `7.2.11` to `7.3.4`
and back and systemd-boot `262-3.fc45` to `262.1-1.fc45` and back.
The downloaded artifacts bind the ISO to its sealed roots, boot
certificate and bootc RPM. The dedicated JSONL receipts match the
accepted stage, update, rollback and shutdown observations. Both
upstream update bases omit ZFS and boot with signed v4l2loopback.

| Profile | ISO SHA-256 | Hosted evidence |
| --- | --- | --- |
| `finite-native` | `ec392bea04be11ba44b968776380aeb5ee1fbad04d64a8d043a45dbdf2dedab7` | [Stable artifact](https://github.com/closure-labs/finite/actions/runs/45918999917/artifacts/15168690054) |
| `finite-native-dev` | `ed619ba3464e4c7e43125e4ef5346473b6201660db10442279396c29592286a6` | [Development artifact](https://github.com/closure-labs/finite/actions/runs/45918999917/artifacts/15167956512) |

The `qualification/native-migration` bookmark contains the
workstation-layout rehearsal. Changes `pmmnzpkr`, `nwsysplz` and
`vvpvlpot` add the exact sparse GPT fixture, old OSTree and new
`root-native` subvolumes, shared home and Nix state, independent LUKS
keyslots, and three isolated failure cases. Change `vyqvysvx` boots
the attached rescue ISO using a one-time entry on later forks so
OVMF preserves the baseline EFI order. Change `pvvmxtkk` reads
each rehearsal checkpoint from the dedicated evidence port. The
local regular-file checks verified GPT and keyslot arithmetic. Run
`45930095266` began after both lifecycle receipts were verified. Its
rescue ISO booted, created the encrypted layout and installed the
Finite OSTree image and Fedora shim/GRUB. The pre-reboot BLS check
stopped the run before any shrink. Finite's default `root-mount-spec`
skips bootc's subvolume detection. Change `olkqxqly` passes the
actual filesystem UUID and `rootflags=subvol=/root` to the fixture
install. Run `45938632142` completed provisioning again, and the
offline BLS search still found no matching entries. Change `ounttrsn`
retains the boot inventory and requires the guest to boot through
Fedora shim/GRUB with the recorded UUID and `/root` before opening
any migration fork. Run `45947216850` exercises that gate.
[First rehearsal artifact](https://github.com/closure-labs/finite/actions/runs/45930095266/artifacts/15171412216)
[Second rehearsal artifact](https://github.com/closure-labs/finite/actions/runs/45938632142/artifacts/15175112266)
[Measured GRUB boot rehearsal](https://github.com/closure-labs/finite/actions/runs/45947216850)

The measured run reached Fedora shim and GRUB and mounted the
recorded UUID with `rootflags=subvol=/root`. Its kernel command
line showed that bootc had selected composefs for the legacy
fixture. The observer rejected that backend before any disk shrink.
Change `mrsrpmmy` gives the disposable rescue image an OSTree
`prepare-root.conf` so the pinned bootc defaults to OSTree for the
legacy archive. The native install continues to pass
`--composefs-backend` explicitly.
[Kernel and boot inventory evidence](https://github.com/closure-labs/finite/actions/runs/45947216850/artifacts/15181206656)

Run `45962209031` tests that backend selection. Change `wmwtptsl`
lets the rehearsal reuse the independent lifecycle input jobs.
The Nix payload and locked RPM started together and passed in
21m53s and 11m59s respectively. The rehearsal runner verified both
same-run inputs before image builds.
[OSTree migration rehearsal](https://github.com/closure-labs/finite/actions/runs/45962209031)

The installed legacy OSTree system passed its GRUB boot, encrypted
`/root` mount, Secure Boot, SELinux and shared home and Nix checks.
On the first recovery fork, OVMF had reassigned the original rescue
entry number to the installed disk. The fork booted the legacy
unlock prompt and timed out before any shrink. Change `mqprssto`
creates an entry for the rescue ISO's exact GPT ESP and fallback
loader and uses it only via BootNext. It keeps the original BootOrder
and rechecks the firmware device path during each fork. Run
`45979289021` tests that selection and the recovery phases.
[Legacy boot and recovery console](https://github.com/closure-labs/finite/actions/runs/45962209031/artifacts/15188365605)
[GPT rescue rehearsal](https://github.com/closure-labs/finite/actions/runs/45979289021)

The GPT rescue entry worked in run `45979289021`. The legacy boot
armed BootNext `0005` for the ISO's EFI partition and the first
recovery fork recorded that exact partition UUID with the original
BootOrder. The fork shrank Btrfs to 504953307136 bytes and the LUKS
mapping to 986368000 sectors, then stopped before the GPT write.
The recovery boot reached Fedora shim, GRUB and the original LUKS
prompt. A kernel message split `passphrase` on the serial console
and the host waited 15 minutes without sending the key. Neither an
unlock result nor a running-root receipt was produced.

Change `kyxlzozn` filters complete kernel messages while matching
LUKS prompts, retains the raw UART and still requires the dedicated
VirtIO boot receipt. Replaying the exact failed console recovers the
prompt for the original UUID. Run `45992389140` checks the rollback
boot and all later recovery forks.
[Shrink and rollback boot evidence](https://github.com/closure-labs/finite/actions/runs/45979289021/artifacts/15193768815)
[Prompt handling retry](https://github.com/closure-labs/finite/actions/runs/45992389140)

Run `45992389140` passed the full workstation-layout rehearsal on
`c2500e1d4be689664132ff330043b72a514ba58c`. The source, seal, media, same-run
payload and all 11 raw guest record files matched the final report. The ISO
SHA-256 was `4b3793eed28042ce924f7bbc9c71d94703dddaf8208470e3808829fb494555e4`.
Each recovery fork selected the rescue ISO by GPT ESP and retained BootOrder
`0003,0000,0001,0002,0004`. The old root booted after the interrupted shrink,
the EFI journal recovery and the missing-loader BootNext. The final fork
created the 4 GiB XBOOTLDR, booted `/root-native` via `0006` with the alternate
keyslot and strict composefs integrity, and returned to the original `0003`
default. The six disk boots preserved the shared home, `/nix` and UID/GID.
The VM used 2 vCPUs and 3072 MiB, with a 3072 MiB host reserve.
[Workstation-layout evidence](https://github.com/closure-labs/finite/actions/runs/45992389140/artifacts/15205435307)

The two producer jobs finished in 11m42s and 22m05s in parallel. The full run
took 2h28m29s. Image and media assembly took 1h34m22s on this runner before the
first rescue phase. All guest phases and final checks took about 29 minutes.
The operator sequence uses the measured geometry and rollback checkpoints.
[Workstation migration runbook](workstation-native-migration-runbook.md)

## Reviewed importer lifecycle and production signing

Both jobs in [run 46061995549](https://github.com/closure-labs/finite/actions/runs/46061995549)
passed on source `4e802ac1ad665fad687d6d26a91f6c96832e4b08` with the locked
canonical importer SHA-256
`59121d7c612836629db48dc3502a22f8ebf64f83625fad512b1b632a3ebb29d2`.
Both retained evidence bundles were compared against their five boot records.
The capped VMs exercised encrypted initial installation, staging before reboot,
booting the upgraded deployment, staging a rollback and booting the restored
deployment. Both exercised kernel `7.2.11-300.fc45.x86_64` to
`7.3.4-300.fc45.x86_64` and back, plus a real systemd-boot update and rollback.
They verified Secure Boot, LUKS, SELinux enforcing, a strict composefs root,
signed ESP and fallback loaders and the preserved `/etc` and `/var` sentinels.
The stable ISO SHA-256 was
`9504c6483894ff4f23bc3d562890e07673e641dda14c3480a1176b992af1079b`.
The dev ISO SHA-256 was
`5e56a63cf455eab0236dfdc539b03bea670603fd53478a1f67a48846bffd27b2`.
Both used disposable signing certificates.
[Stable evidence](https://github.com/closure-labs/finite/actions/runs/46061995549/artifacts/15235731645)
[Dev evidence](https://github.com/closure-labs/finite/actions/runs/46061995549/artifacts/15237484181)

[Production run 46076475582](https://github.com/closure-labs/finite/actions/runs/46076475582)
built unsigned digest
`sha256:15f7711c6ecabb499595a8a7d045f5e91b2950381d6a99257d1a0e450046d1c5`
from main `b46e3ba5c8fb5c23ee452387069a63fb9b0f267f`. The protected signer
verified the importer and bound the root evidence before failing on an empty
credential. The existing environment secret was provisioned on 2026-11-17, and
deployment `8121072108` targeted the `boot-signing` environment on `main`.
The exact ISO job was skipped. The next attempt needs a new build and seal from
the same reviewed main revision and run attempt, then independent verification
of the sealed manifest and its ISO. See [the signing boundary](boot-signing.md).

## Next execution sequence

1. Extend the full-profile checks to cover rejection and rescue recovery on
   exact release artifacts. Carry forward the authenticated evidence and the
   already measured real kernel and loader upgrade and rollback checks.
2. Qualify first-boot account creation, interrupted-install cleanup and
   interactive MOK enrollment. The passing install exercised the scratch
   self-bind and committed the offline EFI journal with pre-enrolled public
   certificates. Qualify recovery-key unlock before the optional FIDO2 path.
3. Wire the native qualifier and protected seal into publication, then widen
   the profile contracts together: `impact.PROFILES`, `payloads.py`, explicit
   selection/matrices, `collect-qualification.py`, `decision_controller.py`,
   security profiles/reuse, `workflow_costs.py`, and their tests. Keep paired
   release coordination's intended profile pair explicit. Do not route a native
   image through Anaconda or treat legacy VM receipts as native evidence.
4. On reviewed main, verify the production-key CI seal, independently imported
   final OCI root/UKI binding, security admission and exact native VM evidence.
   Promote native tags only after those gates pass; verify updater selection of
   a qualifying official bootc release without confusing its runtime with the
   independently pinned canonical importer.
5. After production media qualification, the operator verifies a fresh backup,
   enrolls the production MOK, test-boots rescue media and follows the runbook.
   Keep the old GRUB/rEFInd path and default until hardware update and rollback
   acceptance. The rehearsal used OVMF, synthetic data and synthetic keyslots.

The full-flake Home Manager evaluations were not rerun on this 16 GiB host.
Do not launch parallel builds or VMs to close the remaining gates. Apply the
approved memory watchdog and one-VM limit to subsequent work.
