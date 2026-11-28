# Production boot signing

The production UKI/EFI signer is separate from Cosign image/release signing and
from the existing akmods module-signing MOK. The dedicated GitHub environment
`boot-signing` is restricted to branch `main` and holds only the secret
`FINITE_BOOT_SIGNING_KEY`. SecretSpec's standalone `boot-signing` scope exposes
only that key to an explicit signer child; ordinary shells and other signing
scopes do not inherit it.

Public identity:

- Certificate: [finite-boot.pem](../files/system/usr/share/finite/secure-boot/finite-boot.pem).
- DER SHA256: `e545db8651b876da5a0b21782bf47a0f5365652354435e7b2398b00ac0b67db2`.
- Reviewed metadata: [boot-signing.json](../sources/boot-signing.json).
- Algorithm: RSA 3072, digital signature/code signing; ten-year certificate.

Provisioning completed on 2026-11-17 with explicit operator approval. The
provisioner generated a new key, encrypted its recovery tar to the previously
backed-up SSH Ed25519 public key, successfully decrypted that escrow and compared
the recovered key bytes before uploading the signing secret. It verified the
live branch policy and secret inventory, distributed only the public certificate,
and removed the private working key after success. No production private key is
part of the checkout, image, installer, or CI evidence artifact.

The ciphertext recovery file is
`/var/home/dale/Nextcloud/finite-backup/finite-boot-signer-e545db8651b876da.tar.age`.
Nextcloud automatic upload is assumed as instructed. Its private local receipt
is `artifacts/production-boot-signer/provisioned.json`. The existing
passphrase-encrypted configuration backup contains the SSH recovery key. Keep
that backup's passphrase independently of Nextcloud.

## Recovery

Use a trusted rescue system and a private directory with mode 0700. Restore the
SSH private key from the configuration backup and retain its original mode.
Decrypt the signer escrow with `age --decrypt --identity PATH_TO_SSH_KEY`,
extracting the tar only inside that private directory. Do not print the private
key or place it in an installer, image build context, Nix store path or artifact.

Compare the recovered certificate's DER SHA256 with the metadata above. Derive
the public key from both private key and certificate with OpenSSL and compare
them locally. Recreate the dedicated environment's exact main-only branch
restriction before restoring `FINITE_BOOT_SIGNING_KEY` with `gh secret set`
through stdin. Read back only secret metadata and branch restrictions. Remove
the private working copy after verifying a controlled signing/recovery test.
Recovery does not authorize replacing qualified release artifacts.

## Enrollment and rotation

The public certificate is shipped at
`/usr/share/finite/secure-boot/finite-boot.pem` through both profiles' shared
filesystem module. It has not yet been enrolled on the workstation, and its
presence does not qualify the native release architecture.

For rotation, provision a distinct new key and encrypted escrow with a new
public fingerprint. Never silently overwrite the current identity. Enroll and
test the new MOK while retaining Fedora shim, MokManager and the existing module
MOK. Qualify both profiles and a rollback/recovery path with the replacement
signer before removing the previous trust entry. Retain old public certificates
and recovery escrow for retained artifacts. If a key is compromised, revoke its
trust only after a tested replacement/rescue path is available.

`provision-boot-signer.py` refuses existing production identities/environments.
An interrupted provisioning requires inspecting its private state and encrypted
escrow before any retry. The production certificate is currently marked
`qualified: false` in the signer policy. The exact stable production image and
ISO have passed fresh encrypted installation in the capped VM. Production
lifecycle, hardware coexistence and the release gates remain open.

## Protected sealing boundary

`native-production-validation.yml` calls `image.yml` to build an unsigned
native root. Its `seal` job directly binds the `boot-signing` environment on a
manual run of reviewed `main`. The job validates the workflow ref and consumes
the root digest, build identity and root artifact from the same run and attempt.
Only the sealing step resolves `FINITE_BOOT_SIGNING_KEY`. The environment's
branch restriction is independent of the workflow's own checks.

Run [46076475582](https://github.com/closure-labs/finite/actions/runs/46076475582)
built and imported the unsigned root. GitHub registered a `boot-signing`
deployment for its nested reusable signing job, but the step environment
contained an empty signing credential. The environment metadata confirmed the
named secret had been provisioned before the run. The direct job removes that
workflow boundary and uses the existing protected environment.

Run [46092379577](https://github.com/closure-labs/finite/actions/runs/46092379577)
resolved the production credential in the direct job, signed the EFI binaries,
and verified the signed UKI against a fresh canonical import. The subsequent
registry copy hit `chown .../blobs/sha256: operation not permitted` opening the
outer OCI tar. The keyless upload now extracts the content-addressed blobs as
the runner user and passes the resulting OCI layout to Skopeo. This leaves the
image manifest, layer bytes and layer metadata intact. The revised handoff,
registry copy and exact ISO passed in
[run 46106726545](https://github.com/closure-labs/finite/actions/runs/46106726545).
The [rollout evidence](native-rollout-progress.md#reviewed-importer-lifecycle-and-production-signing)
records the exact digest, ISO checksum and capped VM receipt.

The host toolchain and source archive are prepared before credentials are
resolved. `seal-native.py` strips the key from its environment before any child
process and provides an anonymous, memory-backed key descriptor only to
`faketime` and `sbsign`. The descriptor closes when sealing exits. Image
builds run without signing credentials, and signing work stays outside
retained artifacts. Pinned faketime fixes
the Authenticode timestamp; it does not replace cryptographic randomness.

After independent final OCI import and signature verification, the keyless
upload step replaces only the isolated candidate tag. Source/build/archive
evidence binds the final immutable manifest. Ordinary Cosign image signing,
security admission, encrypted-VM acceptance and paired release approval still
apply. Resuming a candidate requires its original production sealing receipt
and successful original build/seal jobs; it never re-signs an old source with a
new key. See [implementation and remaining gates](v0.9.0-implementation.md).

## Exact production candidate qualification

The manual `native-production-validation.yml` workflow selects one native
profile on reviewed `main`. It builds a fresh isolated candidate and verifies
the canonical importer before the protected job resolves its boot signing
credential. The consumer has read-only registry and Actions access. It pulls
the sealed manifest by digest and independently imports it, then compares the
production certificate, strict root digest and signed UKI hashes with the
protected signer’s receipt. It builds the ISO without changing the product
payload. The standalone `native-iso.yml` path continues to require a Cosign
signature from the release key.

The VM enters the exact ISO through its own firmware boot path and uses a
one-time GRUB command line to open the live serial rescue console. It runs the
normal installer against an isolated qcow2 disk. A separate read-only input
provides the boot observer, which is installed only in that disposable disk's
writable `/etc`. The installed signed UKI retains its command line. QEMU's VGA
console supplies the installer-generated recovery key during the first boot.
The checks bind the running UKI and composefs digest to the original seal,
verify Secure Boot and SELinux, and record the encrypted mounts and EFI update.
Only a successful qualification uploads the exact ISO. Publication, production
MOK enrollment through MokManager and physical acceptance remain separate gates.

The disposable console rehearsal at `96befe78` passed with the production
UKI command line and a temporary signing certificate. The first attempt
reached the installer prompts and timed out before observing a key. The
successful attempt masked the serial getty on the same guest UART as the
debug shell. It exercised the normal encrypted install, entered the
installer-generated recovery key at the graphical prompt, and independently
matched the installed UKI and composefs root to the seal. The guest ran offline
with 2 vCPUs, 3072 MiB memory and a 3072 MiB host reserve. The receipt carries
`validationOnly: true` and records this specific disposable ISO.
[First console attempt](https://github.com/closure-labs/finite/actions/runs/46051724775)
[Console acceptance receipt](https://github.com/closure-labs/finite/actions/runs/46062576108/artifacts/15233010426)

The `qualification/native-production-readiness` branch runs a credential-free
importer check on two ephemeral runners. It can diagnose a pinned executable
mismatch before a production run. The signing job requires the reviewed
executable hash and version even when the Nix output path agrees.

Parallel and serial builds of `bootc 1.17.1` both produced different
executable hashes from the same respective Nix derivations. The ELF
differences first pointed to the Varlink streaming code generated by
`zlink-macros`. The importer derivation sorts its streaming response types
before generating Rust code. A second comparison with matching symbol names
isolated a varying order of bundled PCRE2 objects. The host importer now links
against shared PCRE2 from the pinned Nix package set. The Fedora bootc RPM keeps
its existing source and package checks.

Four fresh hosted runners produced identical complete executables with both
fixes. The verifier lock records their exact SHA-256. The signer and its
independent consumer check it before executing bootc. The disposable lifecycle
jobs verify the same digest before building their first image.
[Serial comparison](https://github.com/closure-labs/finite/actions/runs/46056480996)
[Varlink comparison](https://github.com/closure-labs/finite/actions/runs/46058948884)
[Four-runner importer comparison](https://github.com/closure-labs/finite/actions/runs/46060598229)
[Earlier native media run](https://github.com/closure-labs/finite/actions/runs/45803664314)
[Accepted lifecycle](https://github.com/closure-labs/finite/actions/runs/45918999917)
[Accepted migration rehearsal](https://github.com/closure-labs/finite/actions/runs/45992389140)
