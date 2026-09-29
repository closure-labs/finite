# Workstation qualification and release evidence

## Rollout policy

Candidate build, boot qualification and channel promotion are separate jobs.
Boot qualification is mandatory when the image input identity changes and on
Monday's scheduled build. The workflows enforce it directly; repository variables
cannot turn a failed qualification into a successful publication. Local publication
tools default to enforcement and reject the former `shadow` mode.

A failed qualification or missing, stale or mismatched acceptance record prevents
promotion. Cancelled publication does not promote. The candidate remains available
for diagnosis while public channel tags retain their previous image.

The assembled image must include a nonempty kernel and matching initramfs with
`/init`, OSTree, LUKS and FIDO2 support. Both build finalization and inspection of
the final image check this before qualification. Next-kernel recipes explicitly
regenerate the initramfs after replacing the kernel RPMs.

The September 22, 2026 `finite-dev-next` incident exposed the former shadow-mode
gap: the VM qualification failed at MOK management, but publication proceeded with
`accepted: false`. The image also lacked its replacement kernel's initramfs,
causing encrypted workstations to panic before LUKS unlock. A green historical
workflow alone is therefore insufficient evidence of a successful boot; inspect
the acceptance and promotion records.

## What is qualified

Each candidate is identified by immutable digest, profile, source revision and
`io.finite.build-inputs`. The versioned identity includes image recipes, system
files, scripts, installer/tool locks, relevant workflow definitions and the
evaluated Nix payload derivation. Documentation alone does not alter it.
Recovery checks this identity as well as the Bluefin base and public aliases.
Images without this metadata require one rebuild.

Selection is deliberately conservative: any changed declared image input,
including a changed Home Manager payload, requires qualification. Unchanged
declared inputs can reuse the preceding channel's identity between weekly tests.
Floating DNF and BlueBuild module changes are not captured by this identity;
the weekly qualification exercises their resulting image. Reproducible identity
does not claim bit-for-bit reproducible image output.

Qualification first installs and boots the candidate ISO with enrolled Microsoft
UEFI keys. The harness also pre-enrolls the public module-signing certificate
bundled in the verified ISO into the VM's MOK database. This models a workstation
that has completed key enrollment and avoids the installer's interactive MOK
screen. It preserves Secure Boot settings and verifies both Secure Boot status
and certificate enrollment on each boot. Firmware-variable and certificate
records are retained with the VM evidence. Interactive enrollment itself is not
covered by this unattended test.

Enrollment is checked by exporting the guest's enrolled MOK certificates and
matching the ISO certificate's SHA-256. Do not use `mokutil --test-key` exit
status for this assertion: older releases return one for an enrolled key.
The September 29, 2026 generic-image qualification stopped on that successful
enrollment result even though the guest had booted with Secure Boot enabled.

The same run's DX guests reached SSH but rejected the test account's public key.
Authentication errors are retained separately from connection failures. An
acceptance-only timer writes account status, effective SSH policy, key
fingerprints, file labels and service logs to the serial console after 90 seconds,
so diagnosis does not depend on working SSH. It does not print password hashes
or private keys, or alter the image's authentication policy.

The VM activates Home Manager, checks Nix and captures diagnostics.
When a previous channel digest exists, a second installation starts from that
digest, rejects a wrong signing key, upgrades to the exact candidate digest,
and rolls back while preserving Nix state and user customization. Both the
installed and updated digest are checked against the signed manifest/index.
The VM never resolves a moving public tag as the update target during that test.

A channel without a predecessor records `bootstrap: true`; fresh installation
is mandatory, but no prior-image upgrade is claimed. Qualification takes up to
240 minutes per profile and uses ephemeral GitHub-hosted runners. No private
SSH keys or VM disks are included in evidence artifacts.

### Acceptance VM desktop user

The unattended VM installer creates `finite-test` with UID and GID 1000, matching
Bluefin's first desktop user and its shared Homebrew installation. Without explicit
IDs, Anaconda allocated UID 30011 after the image's Nix build users; Home Manager
activation then failed because Homebrew belongs to `1000:1000`. Qualification waits
for `brew-setup.service` and checks that the test user can write the Homebrew
repository and Cellar before activation. These settings apply only to the test VM.

The explicit IDs use the documented Kickstart [`user` options](https://pykickstart.readthedocs.io/en/latest/kickstart-docs.html#user).

The DX fixture also booted with `default_t` labels on the account's home and SSH
key files, preventing public-key authentication despite correct ownership and
sshd settings. A VM-only prerequisite now restores and verifies the account's
labels using the booted image's policy before starting SSH. Its output is retained
on the serial console; a relabeling failure prevents SSH from starting. SELinux
remains enforcing and the SSH authentication policy is unchanged.

Subsequent DX evidence showed that `restorecon` and `matchpathcon -V` both
accepted `default_t`: generated home rules used `/var/home`, but the vendor
substitution redirected that path to `/home`. Image finalization and the Nix
policy setup now align the substitution with the generated rules, following
the [OSTree home mapping correction](https://github.com/coreos/rpm-ostree/pull/1754).
Policies generated for `/home` retain their existing mapping. The VM additionally
requires `user_home_dir_t` for the account and `ssh_home_t` for its SSH files;
agreement with an incorrect default label cannot pass this prerequisite.

Home Manager activation waits up to fifteen minutes for user services. A cold
Flatpak installation in the September 29 generic VM completed successfully in
126 seconds, just after sd-switch's default two-minute wait had failed activation.
The longer bounded wait preserves synchronous failure reporting; it does not
skip application installation or treat a failed service as successful.

## Kernel maintenance

`sources/kernel-policy.json` defines the approved Fedora tag, kernel series,
architecture, signing key identity and seven-day lag threshold. The daily
kernel workflow proposes reviewed updates to `sources/kernel-next.json`.
It does not auto-merge or cross kernel/Fedora streams. A stream transition,
upstream outage, invalid package or unsigned RPM fails visibly rather than
reporting a successful no-change check.

All five RPMs must download and authenticate before the lock is replaced.
The image build repeats hash, RPM signature and package identity validation
using a temporary RPM database containing only the reviewed Fedora key.
Module checks remain separate: in-tree camera modules must retain their Fedora
kernel signatures. The checked-in kernel version is unchanged by the migration
from unsigned Koji artifacts to their signed counterparts.

Retire the next-kernel override when Bluefin's own kernel passes this same boot
suite and the Dell camera/hardware checks. Review that transition explicitly;
do not remove the fallback channel during an unrelated dependency update.

## Durable releases

Run **Prepare qualified release** on main with an ISO run, a Build Finite run,
the matching channel, and a new `finite-...` release tag. Both source runs must
be successful main-branch runs at the release workflow's source revision. The
qualification must match the ISO's exact image digest and input identity.

The workflow creates a draft release, not an automatic public announcement.
Review and publish the draft to make its assets available to users. Retain
published evidence for the lifetime of the release. The bundle contains:

- ISO bytes, source/installer records and signature verification;
- successful Secure Boot acceptance and publication input records;
- generated Containerfile and release provenance identifying source runs;
- an image SBOM and advisory vulnerability report/status;
- signed checksums covering every asset except the signature bundle itself.

The provenance is Finite release evidence, not a claim of independently
verified SLSA build provenance. The SBOM describes the image, not every package
users may subsequently install through Home Manager or other package managers.
Scanner outages are recorded separately from findings. Findings are advisory;
document accepted exceptions with an owner, rationale and review date in the
release notes before publishing.

ISOs above the release asset size budget are split into numbered parts. Verify
the signature and all checksums before reconstructing the image:

```bash
cosign verify-blob --key cosign.pub --bundle SHA256SUMS.bundle.json SHA256SUMS
sha256sum --check --strict SHA256SUMS
cat finite-bluefin-generic.iso.part-* > finite-bluefin-generic.iso
```

Obtain `cosign.pub` through the established Finite trust process, not merely
from an untrusted copy of the assets being checked. Ordinary ISO artifacts still
expire after seven days; qualification and promotion evidence use 90 days.
Create the durable release before transient ISO artifacts expire.

## Physical hardware checklist

For each hardware release candidate record the image digest, profile, machine
model, BIOS/firmware revision, peripherals, test date and tester. Attach results
to the draft release. Cover at least one supported Intel laptop, one AMD/Mesa
desktop, and the Dell XPS 13 9350 next-kernel target where available.

| Area | Required observations |
| --- | --- |
| Trust and recovery | Secure Boot enabled, SELinux enforcing, signed update and rollback |
| Sleep | Ten lid/suspend/resume cycles on AC and battery; no device loss |
| Power | Record idle and overnight suspend battery loss, duration and workload; compare with the previous qualified image |
| Displays | Internal panel policy, external monitor, dock attach/detach and resume |
| Connectivity | Wi-Fi reconnect after sleep, Bluetooth audio and USB peripherals |
| Media | Speakers, microphone, camera enumeration and browser video capture |
| Authentication | Password login/unlock plus enrolled fingerprint and FIDO paths |
| Persistence | Home Manager customization and Nix state survive update/rollback |

Do not label untested hardware as qualified. Proprietary NVIDIA remains outside
the supported Mesa/Nouveau path; virtual-machine graphics tests do not establish
physical GPU compatibility. Hardware qualification is release evidence rather
than a prerequisite for every pull request.

## Performance measurements

Inspection writes per-profile JSONL timings for registry resolution, pull,
signature verification and runtime checks. Payload staging is measured too.
Where Linux exposes default-interface counters, records include runner network
byte deltas; these include other runner traffic and are not exact process-level
download measurements.
Use Actions job/step timestamps for build, setup, qualification and promotion.
The smaller `.#ci` development shell serves orchestration; the full development
shell remains available locally. Release scanners use a separate shell.

Before changing the remote-pull inspection path or enabling rechunking, collect
at least five equivalent warm runs and one cold run. Record runner image,
source/base digests, cache state, job waiting and transfer measurements. Separate
dependency/concurrency wait from actual runner queueing; do not report summed
job duration as billed cost. Local inspection must prove equivalence to the
published manifest/config and retain remote signature verification.

No local-inspection shortcut or rechunking change is enabled by this rollout.
Transfer-byte attribution, cold/warm benchmarks and physical measurements need
real hosted runs; contract tests cannot establish their performance benefit.
