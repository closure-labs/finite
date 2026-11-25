# Native rollout continuation — 2026-11-25

The [operator-approved Claude plan](plans/PLAN-native-systemd-boot-rollout.md)
selects separate native tags and an operator-run parallel workstation migration.
This record is the continuation point for future agents. Source checks below
are not ISO, VM, release or hardware acceptance. `VERSION` is still `0.8.3-dev`.

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
- Retained the existing [installer research](native-installer-research.md),
  rather than repeating its Anaconda investigation. The installer prototypes
  already implement the custom path; neither has end-to-end qualification.

## Current changes

| Stable jj change | Result | Remaining boundary |
| --- | --- | --- |
| `mtvzotoy`, descendants | Native boot stack rebased onto current main; all five payload inputs and `FINITE_CI_VARS` forwarded | Production-key full-profile qualification remains open |
| `znumxztt` | Separate native recipes, metadata/update channels, build/identity support and native-only runtime staging | Automatic native publication remains closed |
| `xnkqwxpk` | Native media identity checks, disk revalidation, live kernel/scratch fixes and offline EFI transaction | ISO execution, account creation and failure-unwind remain unqualified |
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
`native-image.yml` has the protected root/seal interface and forwards same-run
payload identities, but it is not an enabled native channel publisher.
`publication.py promote` explicitly rejects the native profiles until dedicated
native acceptance exists. Do not remove that guard just to get a green run.

The [installer operator guide](../scripts/native-installer/README.md) describes
the prototype and its gaps. It now targets the correct native tags, verifies the
embedded digest/profile and bootc bytes before disk discovery, excludes active
block-device holders, and revalidates the selected stable ID just before wiping.
It restores the live kernel from `/kernel`, makes target-disk scratch a mount
boundary for bootc's empty-root check, mounts the installed deployment, and uses
its signed EFI payload/certificate and persistent journal. Runtime EFI guards
still reject OSTree and non-strict composefs boots. No disk was written here.

The installer fixes use the exact runtime source, not an assumed CLI:
[bootc mount API at the pin](https://github.com/bootc-dev/bootc/blob/8275daa9227f7c4ee893c0b05b4134dc2ff11283/crates/lib/src/mount.rs),
[empty-root checks at the pin](https://github.com/bootc-dev/bootc/blob/8275daa9227f7c4ee893c0b05b4134dc2ff11283/crates/lib/src/install.rs),
and [image-builder v91.0.0 ISO contract](https://github.com/osbuild/image-builder/blob/v91.0.0/doc/20-advanced/20-bootc/10-isos.md).

## Verification

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
- No ISO build, production seal, encrypted native boot, upgrade/rollback,
  workstation partition/firmware write, MOK enrollment or release occurred.

## Hosted native ISO qualification

The workstation had approximately 27 GiB of free storage and 4.3 GiB of
available memory at preflight. The requested 3 GiB guest plus 3 GiB host
reserve needs a different host. The upstream repository's disposable
`qualification/native-iso` branch builds one full profile at a time and
runs one VM, with two vCPUs and 3 GiB RAM. It boots the built ISO under
Secure Boot OVMF, supplies the ordinary installer prompts over serial, and
reboots the newly installed qcow2. Read the media and guest identities
from the workflow artifacts. [Active retry](https://github.com/closure-labs/finite/actions/runs/45707828686)

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
shared verifier. All 62 Bluefin policy cases passed. GitHub run `45707828686`
is pinned to `b82116d1`, which uses the same locked base digests and predates
the extra verifier and test-only commits.

A capped re-seal of a historical Fedora fixture with the proper explicit
`rw` argument passed independent OCI import and UKI verification. Its
bootable root matched
`9c13a50e83b3452c669bc42671031205697b6bb741d025d9ba33ced6f297826d467b8d500e78fc084282f64dfe507f8b65d3b5f6f032d6410efba2a4e51bc0bd`.
The local fixture demonstrates the importer and sealer cleanup changes.
The full-profile results must come from the hosted VM jobs.

## Next execution sequence

1. Finish native candidate qualification before widening publication. Adapt the
   existing `scripts/vm-composefs` harness to both full native profiles and the
   actual encrypted native installer. Require authenticated exact-image,
   source, importer, certificate and ISO identities; enforcing Secure Boot and
   SELinux; encrypted-root discovery; UKI placement on XBOOTLDR; persistent
   configuration; real kernel/loader upgrades; rollback; rejection and recovery.
   The prior small unencrypted fixture does not establish these properties.
2. Finish and qualify first-boot account creation and interrupted-install cleanup.
   Test the self-bind scratch boundary and offline EFI mount/journal in actual
   media. Test MOK enrollment without private keys on the ISO. FIDO2 remains
   optional/unqualified: retain passphrase/recovery-key unlock first.
3. Wire the native qualifier and `native-image.yml` into publication, then widen
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
5. Rehearse the exact workstation layout in one capped, file-backed VM: 600 MiB
   ESP, 2 GiB ext4 old `/boot`, LUKS2 Btrfs old root/home, preserved GRUB path,
   offline filesystem/mapping/partition shrink, 4 GiB VFAT XBOOTLDR and a new
   `root-native` subvolume. Prove signed root-subvolume discovery, numeric
   ownership, Nix/home preservation and interruption/old-root recovery. Derive
   sector geometry from the fixture; no generic hardware shrink command is
   qualified yet. Never substitute `to-existing-root` on the workstation.
6. Only after the VM rehearsal, write the exact hardware runbook. The operator
   verifies a fresh backup, enrolls the production MOK, test-boots rescue media
   and executes partition/firmware changes from rescue media. Keep the old
   GRUB/rEFInd path and default until hardware update/rollback acceptance.

The full-flake Home Manager evaluations were not rerun on this 16 GiB host.
Do not launch parallel builds or VMs to close the remaining gates. Apply the
approved memory watchdog and one-VM limit to subsequent work.
