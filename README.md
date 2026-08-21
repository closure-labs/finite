# Purplefin

Purplefin turns a typed Nix profile graph into signed, updateable
[bootc](https://bootc-dev.github.io/bootc/) workstation images based on
[Bluefin Stable](https://projectbluefin.io/).

You get four lightly layered foundation images, eight Nix/Home Manager role
profiles, a graphical installer, verified updates, and signed release
artifacts. The foundations preserve the complete upstream Bluefin or Bluefin
DX package set, including Tailscale. Determinate Nix and its SELinux policy are
installed in every image and are ready after first boot.

## Run Purplefin

On an existing bootc system, switch to the generic workstation image:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:latest
run0 systemctl reboot
```

Stay current with:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

For a fresh machine, follow the [graphical installation guide](docs/installation.md).

## Build Purplefin with Nix

Install Nix with Flakes enabled and rootless Podman, then run:

```bash
git clone https://github.com/declarative-dale/purplefin.git
cd purplefin
nix shell --accept-flake-config .#ci-image-build \
  -c purplefin-image-build bluefin-generic localhost/purplefin:bluefin-generic
```

Format and validate the complete repository with the pinned toolchain:

```bash
nix develop
nix fmt
nix shell --accept-flake-config .#ci-check -c purplefin-ci-check
```

## Choose a foundation and home profile

| Home profile | Foundation | Purpose |
| --- | --- | --- |
| `sales`, `executive` | Bluefin | Less technical roles |
| `developer`, `support`, `it`, `trainer` | Bluefin DX | Technical roles |
| `dale` | Bluefin DX, Dell XPS 13 9350 | Superset of every role |
| `elad` | Bluefin DX, generic x86-64 | Every role without the Dell camera layer |

Apply a role to the installer-created user:

```bash
nix run github:declarative-dale/purplefin#home-switch -- \
  --profile support --hardware generic-x86_64
```

After activation, `nh home switch --update-input purplefin` performs later
manual updates from the generated per-user Home Manager flake. A generated
NoCloud seed can perform the initial activation; see the
[installation guide](docs/installation.md).

List every generated profile and published tag with:

```bash
nix build .#generated
jq '.profiles | with_entries(.value = .value.tags)' \
  result/bootc/generated/profile-catalog.json
```

## Learn more

- [Documentation guide](docs/README.md)
- [Changelog](CHANGELOG.md)
