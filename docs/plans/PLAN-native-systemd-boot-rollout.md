# Approved rollout plan (2026-11-25)

Retained operator-supplied Claude plan. This is the plan as supplied, not a
completion claim. Read the [current continuation record](../native-rollout-progress.md)
first for completed work, preserved branches and remaining gates. Later decisions
in this plan select separate native tags and an operator-run parallel migration;
they supersede older wording that replaces the default OSTree channels.

# Native systemd-boot rollout and Doppler removal

## Context
The native bootc work (jj change `mtvzotoy`, plus `znvxoqxs` on top) builds composefs images that boot without GRUB: Fedora shim → signed systemd-boot → signed UKI. It hasn't merged yet and is based on an old `main` (55d935c), which has since gained 244 commits.

**Workstation as found:**
- It already boots this chain as a one-shot trial: entry Boot0002, `finite-trial.conf`, with a trial MOK enrolled.
- It is still an OSTree system, with GRUB and rEFInd first in BootOrder.
- Disk: a 600M ESP, a 2G ext4 `/boot` (not XBOOTLDR), and LUKS2 + FIDO2 btrfs on the rest of a 512 GB NVMe, with no free space.

**Gaps:**
- No installer can install the native system. The ISO path is unchanged Anaconda + OSTree + GRUB, and the native work removes `bootupd`.
- The work currently makes the default `finite` and `finite-dev` tags native, which would break existing OSTree installs.

**Your decisions:**
- Native images go under **separate tags**.
- **Research Anaconda first** before building a custom installer.
- Migrate the workstation with the **documented parallel install**: offline shrink, a 4 GiB XBOOTLDR, and a new root subvolume next to the old one, with GRUB kept for rollback.

You also asked to remove the Doppler pilot from GitHub, using the signed-in browser, and then from CI.

All builds and VM runs use the agreed limits: nix `--max-jobs 1 --cores 2`, `nice 19`, the memory watchdog, and one VM at a time.

## Phase 0: Doppler removal (independent; first)
1. **Browser, github.com/closure-labs/finite settings.** Read-only checks found the environment has no secrets or variables.
   - Delete the `doppler-pilot` environment. This is permanent.
   - Under Actions → General → allowed actions, remove `DopplerHQ/secrets-fetch-action@*`.
   - Look at org-level Actions secrets and variables for anything Doppler-related; `gh` gets a 403 there. I'll report what's there and delete nothing without asking.
   - Anything on Doppler's side (the OIDC service account) is outside GitHub, so I'll flag it for you.
2. **CI change**, on a new branch `doppler-removal` from `main` once #425 has merged:
   - Remove the `doppler-pilot` environment and the DopplerHQ pattern from `automation/github/repository-security.json`, `tests/fixtures/repository-security/pass.json` and `drift.json`.
   - Move `docs/doppler-pilot-setup.md` and `docs/doppler-oidc-assessment-2026-10-13.md` to `archive/docs/` and fix the links in `docs/reports.md`, `release-implementation-sequence.md`, `validation-remediation-plan.md` and `nix-workflow-resources.md`.
3. **Verify:**
   - `gh api` shows the environment and the pattern are gone.
   - The `repository-security` and `bluebuild` check groups and the markdown link check pass.
   - Then open a PR, with Auto-fix on. The `/decider approve` review is posted only when you say so.
   - The scheduled repository-security audit may report drift between the GitHub change and the merge. That's expected.

## Phase 1: Rebase the native work onto main
- `jj rebase` `mtvzotoy` and `znvxoqxs` onto `main@origin` (after #425 merges), then resolve the known overlaps:
  - `publication.yml`: `native-image.yml` must forward the new `payload_*` inputs and `FINITE_CI_VARS`.
  - `image.yml`, `scripts/bluebuild/publication.py`, both recipes, `lib/bluebuild-checks.nix`, `lib/check-sources.nix`.
  - The tests in `tests/bluebuild/{contracts,resume}.py` and `tests/ci/{decision-controller,reuse-candidate-security,secretspec,workflow-costs}.py`.
- Check that the #425 changes still hold for the native files: the review-app-token action, inline disk cleanup in `boot-signing.yml`, the 08:47 cron, and the archived experiments.

## Phase 2: Separate native tags
- Put `recipes/finite.yml` and `recipes/finite-dev.yml` back to the OSTree setup (`initramfs@v1`, `bootupd`).
- Add `recipes/finite-native.yml` and `recipes/finite-native-dev.yml`, using `shared/native-root.yml` and the `io.finite.boot-architecture: native-composefs` label.
- `publication.yml` routes the native profiles through `native-image.yml` (root, then the `boot-signing` seal) and the default profiles through `image.yml` as today.
- Widen the hard-coded profile lists to cover the native profiles. They live in `scripts/ci/impact.py` (PROFILES), `collect-qualification.py`, `publication.py`, the selection and matrix code, and their tests; I'll enumerate the rest with grep.
- **Qualification for the native profiles:** turn the existing `scripts/vm-composefs` harness into a CI job that installs with XBOOTLDR and boots OVMF with Secure Boot. Publish native tags only once it passes. The OSTree ISO and VM qualification stay on the default profiles.
- **Verify:**
  - All check groups pass locally.
  - The native VM harness passes locally in one capped VM.
  - After merge, the first `main` run seals with the production key, and `verify-native-oci.py` passes in CI.

## Phase 3: Installer research (time-boxed), then a decision
Questions to settle with primary sources (Fedora 44 Anaconda docs and source, bootc and bootc-image-builder docs):
- Can Anaconda's `bootc` kickstart command, or `bootc-image-builder --type anaconda-iso`, install the composefs backend with `--bootloader systemd`, an XBOOTLDR partition, LUKS2, and shim + MOK Secure Boot?

Deliverable: `docs/native-installer-research.md` with the findings and a recommendation. Then I ask you to choose: an Anaconda kickstart path for native profiles in `iso.sh`, or a custom installer built from `scripts/vm-composefs/install-xbootldr.sh`. No installer gets built before that choice.

## Phase 4: Workstation parallel-install migration
Prerequisites:
- Phase 2 merged and a production-sealed `finite-native` image published.
- **You** enroll the production MOK from `finite-boot.pem` (SHA256 `e545db86…`) with `mokutil --import` and MokManager.
- **You** build rescue media and test-boot it.
- A fresh `scripts/workstation/backup-local.sh` run with `recovery-backup.py verify`.

1. **VM rehearsal of the exact layout.** Extend `scripts/vm-composefs` with a fixture matching the workstation: 600M ESP, 2G ext4 `/boot`, LUKS2 btrfs with `root` and home subvolumes, booting OSTree through GRUB. Then rehearse the documented sequence from `docs/v0.9.0-implementation.md`:
   - shrink offline in order: btrfs, LUKS mapping, partition;
   - create a 4 GiB VFAT XBOOTLDR;
   - make a new `root-native` subvolume and run `bootc install to-filesystem --composefs-backend --bootloader systemd` into it from rescue media (never `to-existing-root`);
   - carry over the UID/GID and config, and set up root discovery on the cmdline. **FIDO2 unlock may be disabled for the migration (your call, 2026-11-25):** the native root unlocks with the passphrase and recovery key first, and FIDO2 is re-enrolled (`systemd-cryptenroll --fido2-device=auto`) only after a VM test proves token unlock works under a sealed UKI without per-machine `rd.luks.*` arguments;
   - boot it once via BootNext, run `systemd-boot-preflight.py` in full mode, and confirm GRUB still boots the old root;
   - test recovery from an interrupted run.

   Write it up as `docs/workstation-native-migration-runbook.md`, with the exact commands, checkpoints and rollback.
2. **Hardware run, done by you with the runbook from rescue media.** I don't run partitioning or firmware changes on the workstation myself. I'll check each checkpoint's output as you go.
3. **Acceptance, then switch the default.** Only after hardware acceptance: put the native entry first in BootOrder. Remove GRUB/rEFInd as a separate, later step, keeping shim, MokManager, the module-signing MOK and the rescue media.

## Verification summary
- **Phase 0:** GitHub API checks, the local check groups, and a PR.
- **Phases 1–2:** all local check groups, the capped native VM harness, then the CI seal and verify on `main`.
- **Phase 3:** a research doc and your decision.
- **Phase 4:** the VM rehearsal runbook passes end to end before anything touches the hardware.
