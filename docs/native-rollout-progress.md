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
- BlueBuild 0.9.37 could not fetch its schema endpoint, including a retry outside
  the restricted sandbox. Recipe schema validation is **not passed**. The
  repository's YAML/recipe contracts passed; resolve schema access and run the
  real validator before integration.
- No ISO build, production seal, encrypted native boot, upgrade/rollback,
  workstation partition/firmware write, MOK enrollment or release occurred.

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
