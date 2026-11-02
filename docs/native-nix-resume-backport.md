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

The source is revision `240bbbcb10d3fc4bce957fafc1000b85ffb004d0`, with its own
locked Nixpkgs graph. The existing component API overrides only libnixstore's
patch phase. It verifies both original and patched source hashes. The patch
bytes match the successful controlled native run
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

## Required hosted validation

Normal PR validation boots both profile images with the existing Secure Boot,
encrypted-root, SELinux and required Home Manager/Homebrew checks. The signed
NAR functional fixture tests ordinary and complete-body/416 substitution,
unsigned and unknown-key rejection, and corrupted data rejection. It uses
ephemeral fixture keys and per-command trust in disposable guests only; no
private key or persistent trust setting is retained in artifacts.

For relevant Nix changes, the finite job reuses that exact candidate ISO for a
second installation. It preloads the immutable Nix seed from a digest-pinned,
signature-verified published predecessor. First boot must replace that old
client, preserve its Nix state/certificates, and run the fixed daemon. A second
boot must retain the same fixed runtime before functional checks run. Metadata
records the predecessor digest and seed archive hash. This is persisted-Nix
migration coverage, not a signed OS update/deployment or a kernel-transition
claim. The finite-dev profile receives normal fresh coverage, not a separate
persisted-state cohort.

The finite premerge image job is capped at 150 minutes, finite-dev at its
existing 120 minutes. ISO creation is not repeated for the second finite VM.
No production signing/promotion action is part of this draft validation.
