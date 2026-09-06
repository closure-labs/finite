# Develop Finite

Use a Finite checkout with Nix and BlueBuild CLI v0.9.37. Keep full image builds,
ISO generation and VM tests on GitHub-hosted runners; local checks and recipe
validation are the lightweight development path.

## Choose where to make a change

| Change | Files |
| --- | --- |
| Image foundation, tags or profile identity | `recipes/*.yml` |
| Shared image packages and modules | `recipes/shared/` |
| System configuration and vendor units | `files/system/` |
| RPM repository definitions | `files/dnf/` |
| Nix lifecycle and kernel installation | `files/scripts/` |
| Home Manager apps, roles and settings | `templates/home-manager/modules/aspects/` |
| Profile choices and compatibility | `lib/domain-catalog.nix` |
| Determinate, kernel and installer pins | `sources/` |
| Build, ISO and VM integration | `scripts/bluebuild/` and `.github/workflows/` |
| CI change selection and required gate | `scripts/ci/` and `tests/ci/` |

The four handwritten recipes are the image configuration. Shared `from-file`
modules keep common packages, assets and services together. Nix produces the
Home Manager template/catalog and pinned installation payload.

## Run local checks

Inspect downloads before starting a build, then cap local jobs and cores:

```bash
nix build --accept-flake-config --dry-run .#ci-checks
nix build --accept-flake-config --max-jobs 1 --cores 1 --no-link .#ci-checks
nix fmt
```

The checks cover Home Manager configurations, Nix lifecycle, kernel and installer
contracts, UEFI ISO layout, dependency updates, formatting, workflow linting and
repository policy. For a focused run:

```bash
nix build --accept-flake-config --max-jobs 1 --cores 1 \
  --no-link .#checks.x86_64-linux.bluebuild --print-build-logs
```

Use the pinned development shell for Python tests and workflow tools:

```bash
nix develop --accept-flake-config --command python3 tests/ci/selection.py
nix develop --accept-flake-config --command python3 tests/bluebuild/contracts.py
```

Validate a recipe and inspect its generated Containerfile:

```bash
bluebuild validate recipes/bluefin-generic.yml
bluebuild generate --registry ghcr.io --registry-namespace closure-labs \
  recipes/bluefin-generic.yml
```

Before an image build, run `bash scripts/bluebuild/stage.sh PROFILE`. This stages
`files/payload` for the selected recipe. The next profiles include the locked
kernel RPMs. The hosted build workflow performs staging automatically.

## Work on Home Manager

The portable modules and assets live in `templates/home-manager`. To add a role
or optional package, update `lib/domain-catalog.nix`, implement its aspect, and
run the checks. The catalog supplies the selectors, profile validation and
Home Manager configuration proofs.

Inspect the runtime catalog with:

```bash
nix build .#home-profile-catalog
jq . result
```

The image records its foundation, hardware, channel and kernel in
`/usr/share/finite/profile.json`. First login combines that identity with the
user's selected Home Manager environment.

## Validate an ISO

Dispatch [Test ISO in UEFI VM](https://github.com/closure-labs/finite/actions/workflows/vm-acceptance.yml)
with a successful ISO run ID. The hosted test verifies the artifact and
signature, installs in a disposable UEFI VM, activates Home Manager, tests
wrong-key rejection, updates the signed channel and rolls back. It checks Nix
persistence, the running kernel and root remounting on each boot.

The Actions log streams the guest console. The installer has a 45-minute limit;
Nix initialization has a three-minute readiness window after SSH starts.
Artifacts retain service logs, kernel reports, mount layouts and bootc status.

Run generic and next acceptance tests for image or installer changes. Validate
graphics, PipeWire camera, Espanso, suspend/resume and authentication separately
on the target workstation, retaining its previous deployment.

## Verified BlueBuild baseline

| Check | Evidence |
| --- | --- |
| Four signed sandbox images and final-image assertions | [Build 34007974907](https://github.com/closure-labs/finbox/actions/runs/34007974907) |
| Four images built with read-only publication permissions | [Validation 33999999603](https://github.com/closure-labs/finbox/actions/runs/33999999603) |
| Generic ISO and complete UEFI acceptance | [ISO](https://github.com/closure-labs/finbox/actions/runs/34005801360), [VM](https://github.com/closure-labs/finbox/actions/runs/34006462352) |
| Next-kernel ISO and complete UEFI acceptance | [ISO](https://github.com/closure-labs/finbox/actions/runs/34006463272), [VM](https://github.com/closure-labs/finbox/actions/runs/34007158009) |

Both VM runs passed first boot, Nix/SELinux, Home Manager, signature rejection,
updating, persistence and rollback. The hosted AMD processors report the
inherited `mcelog` diagnostic service as unsupported. Physical hardware checks
form a separate acceptance step.

The upstream reference revisions used for this implementation are recorded in
[reference-revisions.json](bluebuild/reference-revisions.json).
