# Develop Finite

Use a Finite checkout with Nix and BlueBuild CLI v0.9.37. Keep full image builds,
ISO generation, aggregate Nix evaluation and VM tests on GitHub-hosted runners.
Use already available tools for small local fixture tests and source review.

## Choose where to make a change

This is a Jujutsu (`jj`) repository with colocated Git metadata. Use `jj` for
local changes, bookmarks and rebasing; GitHub Actions still uses Git checkouts.
Start with `jj status` and `jj log`, preserve any existing work, then fetch with
`jj git fetch --remote origin`. Create a separate change on `main@origin` with
`jj new main@origin` when starting independent work. Describe each focused
change with `jj describe`, review it with `jj diff`, and run the checks below.
Use a named bookmark for a pull request and push that bookmark explicitly with
`jj git push --bookmark NAME`. Use GitHub CLI for PR review and CI inspection.
Do not reset the colocated Git working tree or overwrite unrelated jj changes.

| Change | Files |
| --- | --- |
| Image foundation, tags or profile identity | `recipes/*.yml` |
| Shared image packages and modules | `recipes/shared/` |
| System configuration and vendor units | `files/system/` |
| RPM repository definitions | `files/dnf/` |
| Nix lifecycle and upstream kernel preservation | `files/scripts/` |
| Home Manager apps, roles and settings | `templates/home-manager/modules/aspects/` |
| Profile choices and compatibility | `lib/domain-catalog.nix` |
| Determinate, upstream image trust and installer pins | `sources/` |
| Build, ISO and VM integration | `scripts/bluebuild/` and `.github/workflows/` |
| CI change selection and required gate | `scripts/ci/` and `tests/ci/` |

The two active handwritten recipes are the image configuration. Shared `from-file`
modules keep common packages, assets and services together. Nix produces the
Home Manager template/catalog and pinned installation payload.

## Run checks

The hosted Build Finite workflow runs the pinned aggregate Nix checks and formats
the source. Nix evaluation itself has exhausted workstation memory, including
before a build started. Do not run aggregate evaluation, `nix develop`, devenv
aggregate tests or VM/image operations on this workstation. Job/core limits
alone do not bound evaluator memory.

The checks cover Home Manager configurations, Nix lifecycle, kernel and installer
contracts, UEFI ISO layout, dependency updates, formatting, workflow linting and
repository policy. For a focused local fixture, use an already installed Python
with the test's dependencies, without realizing another shell:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 tests/ci/release-request.py
```

On a suitably provisioned development host, validate a recipe and inspect its
generated Containerfile with an already installed BlueBuild CLI:

```bash
bluebuild validate recipes/bluefin-generic.yml
bluebuild generate --registry ghcr.io --registry-namespace closure-labs \
  recipes/bluefin-generic.yml
```

Before an image build, run `bash scripts/bluebuild/stage.sh PROFILE`. This stages
`files/payload` for the selected active recipe. Both variants preserve the
approved upstream kernel and modules. The hosted build workflow performs staging
automatically.

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

Run standard and developer acceptance tests for image or installer changes. Validate
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
