# CI and publishing

`recipes/*.yml` authoritatively define four independent BlueBuild images. The
workflow builds Bluefin and Bluefin DX `stable` channels daily and on main pushes,
PRs, merge groups and manual dispatches. The pinned action is BlueBuild v1.12.0
(`836161eb076426a451e6a0054f722b1153b8b3ad`) and the CLI is v0.9.37.

The `CI gate` requires both the Nix/runtime checks and every image job to pass.
Read-only validation and trusted publication each call the same four-profile
reusable workflow with fixed inputs and token permissions. They use the same
Docker build mode; rechunking is disabled. Failed
profiles do not cancel the others. Only trusted main runs in `closure-labs/finite`
receive registry write permissions and `COSIGN_PRIVATE_KEY`. Validation uses its
read-only job token for registry authentication. PR and merge-group builds
neither publish nor receive signing secrets. Publication runs serialize
under `finite-publication`; successful profiles publish independently through
the upstream action, including its cache and signature handling.

The CLI's named Docker builder uses `default-load=true`, making nonpublishing
builds available for final inspection on the runner. Publication uses the
upstream action's explicit registry output with the same builder configuration.

BlueBuild resolves upstream digests during generation/build. Image evidence
artifacts retain final labels (including base digests), image references,
signature verification and generated Containerfiles for review. The generated
review Containerfile resolves the current stable digest; the final image's
base-digest label records the actual build input if upstream changes mid-run.
Checks run inside the assembled image after BlueBuild cleanup, explicitly
verifying the immutable Nix seed under `/usr` and running `bootc container lint`.

Cosign uses a key pair. `cosign.pub` is tracked; the private key is an Actions
secret and must never enter Git, Nix derivations, build contexts or artifacts.
To rotate the signing key, generate it outside this repository with
`COSIGN_PASSWORD='' cosign generate-key-pair`, install its private half with
`gh secret set COSIGN_PRIVATE_KEY --repo closure-labs/finite < cosign.key`, and
replace the public half in the repository. Validate signatures and host policy
before any signature-enforced bootc switch. Package visibility must
permit the installer to pull the image.

Nix dependency updates and the Determinate checksum lock update remain
available. The repository policy allows
the pinned BlueBuild action and its transitive actions.

Use the manual **Build installation ISO** workflow with a channel and a verified
image digest. Each ISO gets a unique immutable-intent installation tag, source
record, signature evidence and SHA-256 checksums. See
[installation](installation.md) for selecting the ongoing update channel.
