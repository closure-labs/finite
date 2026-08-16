# Self-hosted cache runner

Purplefin's optional self-hosted runner is a cache warmer, not a release
publisher. The `Warm bootc build cache` workflow runs repository checks, builds
the common base, hardware parents, and role deltas on the trusted
`purplefin-builder` runner, and rechunks each result. It exports Buildah layers
to `ghcr.io/declarative-dale/purplefin-build-cache` and build-input-keyed,
rechunked images to `ghcr.io/declarative-dale/purplefin-stage-cache`. It also
generates each stage's SPDX JSON once and stores it in
`ghcr.io/declarative-dale/purplefin-sbom-cache`, with the stage digest recorded
in the artifact metadata.

The normal `Build Purplefin` workflow always runs on GitHub-hosted runners. It
prefers an exact rechunked stage whose labels match the requested source,
profile, upstream digest, and immutable parent. It performs the complete build
and rechunk itself when no valid stage exists. A missing local runner therefore
never blocks image publication. On a hit, ORAS copies the stage digest between
GHCR repositories without downloading the image and applies every channel tag
as an alias of that digest. Hosted jobs remain responsible for signatures and
GitHub attestations; they reuse the validated cached SBOM or generate and cache
one after a hosted fallback build.

The host needs:

- the official GitHub Actions runner registered with the custom
  `purplefin-builder` label;
- Nix with flakes enabled;
- Podman, Buildah, Skopeo, Git, and `jq`;
- enough container storage for the Bluefin parent and the base build.

Only cache-only workstation jobs write stage-cache tags, preventing hosted and
local builds from racing to replace them. Cache-only jobs remove their local
result, stage-cache tags, and Buildah cache tags after the remote image and SBOM
exports complete. Parent layers may remain only while another local image still
references them. The manual package-cleanup workflow removes untagged and
retired stage/SBOM cache versions while preserving every current build input.

The flake-pinned Syft package is mounted into the pulled stage image and scans
its merged root filesystem with a 4 GiB container limit. This avoids retaining
the registry's full layer graph in the runner process and keeps scanner tooling
out of the resulting SPDX inventory.

Only trusted `main` pushes and manual dispatches target this runner. Do not add
`pull_request` to the cache-warmer workflow: a self-hosted runner must not run
untrusted pull-request code.

Inspect or control the local service with:

```bash
systemctl --user status purplefin-github-runner.service
systemctl --user restart purplefin-github-runner.service
systemctl --user disable --now purplefin-github-runner.service
```

The GitHub repository's **Settings → Actions → Runners** page can disable or
remove the registration independently of the local service.
