# Self-hosted cache runner

Purplefin's optional self-hosted runner is a cache warmer, not a release
publisher. The `Warm bootc build cache` workflow runs repository checks and the
shared base build on the trusted `purplefin-builder` runner, then exports
Buildah layers to `ghcr.io/declarative-dale/purplefin-build-cache:base`.

The normal `Build Purplefin` workflow always runs on GitHub-hosted runners. It
uses the warmed cache when available and performs the complete build when the
workstation is offline. A missing local runner therefore never blocks image
publication.

The host needs:

- the official GitHub Actions runner registered with the custom
  `purplefin-builder` label;
- Nix with flakes enabled;
- Podman, Buildah, Skopeo, Git, and `jq`;
- enough container storage for the Bluefin parent and the base build.

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
