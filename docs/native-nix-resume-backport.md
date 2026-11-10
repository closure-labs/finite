# Native completed-download recovery draft

Determinate Nix 3.24.1 can receive a complete HTTP response body, lose the
terminal chunk/stream marker, and resume at the completed length. Its HTTP 416
response then fails substitution. The temporary native backport accepts only
a successful GET transfer with prior bytes and a valid Content-Range total
exactly equal to the delivered length. Other 416 responses remain errors.

Upstream: NixOS/nix#16722; DeterminateSystems/nix-src#750. Recheck releases before
merging. The installer-version assertion deliberately blocks a newer installer
from silently being combined with this older runtime; remove the backport when
the released fix and its guest behavior are verified.

## Source and runtime

The 3.24.2 candidate source is revision `f43bee4f45c2d42e7d1f4e37908ec5c7bb0fdba1`, with its own
locked Nixpkgs graph. The existing component API overrides only libnixstore's
patch phase. It verifies both original and patched source hashes. The patched source bytes match the successful controlled native run
<https://github.com/closure-labs/finite/actions/runs/41370314883>.

The image carries the runtime closure, native closure registration and hashes
of the executable and library. As with the existing installer seed, the OS
signature authenticates these local files. The native registration API and
`nix-store --verify-path` import/check that seed; no network substitution
signature flag, public trust key or global cache policy is changed.

Fresh image assembly installs the runtime into the existing default profile.
Before daemon startup, a service also migrates preserved Nix state, checks all
closure hashes, and uses native nix-env profile replacement. Existing store
bytes are never overwritten. Certificates must remain byte-identical. Unknown
profile formats fail closed. Nixd uses the same default profile to spawn the
daemon. Guest checks independently bind both the client and running daemon ELF
and libnixstore to the image's expected hashes.

## Validation and normal pipeline

Ordinary PR updates retain the full source/runtime checks. The protected merge
queue performs selected fresh-image VM validation, including Secure Boot,
encrypted root, SELinux and required Home Manager/Homebrew checks. The signed
NAR fixture covers ordinary and complete-body/416 substitution, unsigned and
unknown-key rejection, and corrupted data rejection. Its keys are ephemeral,
with per-command trust in disposable guests only.

The focused integration preserves these entry points and the existing queue
time limit. It does not add the isolated branch's manual-dispatch routing or
force another persisted-state VM into the queue. The existing PR-local
predecessor fixture receives its inert, never-started container command fix.

Verified hosted evidence is retained separately:

- [Finite fresh installation and preserved-Nix migration](https://github.com/closure-labs/finite/actions/runs/41408057981):
  the digest-pinned, signature-verified predecessor client was replaced, its
  state remained after reboot, and client/daemon hashes and SELinux types matched.
  Both cohorts passed all five signed-NAR controls using the same candidate ISO.
- [Finite-dev host-space validation](https://github.com/closure-labs/finite/actions/runs/41431341112):
  source checks, fresh installation, signed-NAR controls and functional
  initialization passed. Native runtime hashes matched the finite evidence.

These are isolated guest validations, not signed production OS-upgrade,
deployment or kernel-transition proof. Production signing and promotion remain
subject to the existing independent gates. An updated PR head requires fresh
human review; retained results do not replace that authority.

## 3.24.2 coordinated candidate

The installer and native runtime pins move together to 3.24.2. The upstream
completed-resume fix is not yet merged, so the backport remains. The 3.24.2
filetransfer.cc bytes match the original guarded hash, and the unchanged patch
still produces the guarded patched hash. Both version/revision assertions and
all migration, signature and guest checks remain required.

The hosted evidence above is historical 3.24.1 evidence, not validation of this
candidate. Fresh installation, preserved-state migration and all signed-NAR
controls must pass for this new runtime before merge is recommended.

## Host-space handling

Local validation removes only its owned OCI export after successful ISO
construction and checksum recording. It preserves the ISO and manifests for
subsequent VM use. Before functional initialization, it reclaims only unused
cache from this job's completed, named `bluebuild` builder using native Buildx
free-space targeting. It then checks actual free host bytes and requires
30,000,000,000 bytes after the guest disk has been installed.

Successful finite initialization grew host-backed VM state by up to 19.1 GB;
the threshold leaves about 10.9 GB of margin without claiming a universal
future workload bound. An unsuccessful prune, unavailable measurement or
insufficient space fails before initialization. Guest disks, Docker images,
Nix stores and production publication cache policy are preserved.

The finite-dev validation reported 9.068 GB reclaimed, measured about 34.48 GB
free before initialization and retained about 15.31 GB afterward. These are
resource measurements, not an end-to-end performance comparison. Disk snapshots
remain bounded, and initializer capture retains its 256 MiB compressed limit.
Evidence-storage errors stay fail-closed while draining guest output so a
diagnostic failure does not conceal the guest verdict.
