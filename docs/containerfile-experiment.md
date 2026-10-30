# Unpublished Containerfile experiment

This is an opt-in architecture comparison, not a replacement deployment path.
Production still builds and signs through BlueBuild, then uses the existing
security, qualification, ISO and publication gates. Neither production recipes
nor the production build/publish workflow are changed by this experiment.

## Question and boundaries

Would a plain Containerfile make FINite easier to maintain without losing its
Bluefin integrations? The [Universal Blue image template](https://github.com/ublue-os/image-template)
uses a context stage and a build script; this experiment follows that structure.
It does **not** demonstrate faster builds, boot equivalence, or lower maintenance
cost merely by assembling an image. No registry credentials, push, image signing,
release tag, production promotion, ISO generation or deployment is involved.
The resulting image is unsigned and local to an ephemeral CI runner.

## One source for the desired operating system

`experiments/containerfile/parity.json` records the reviewed semantic shape of
both profile recipes and their shared base/final recipes. `prepare.py` fails
closed when that shape changes. Base and Cosign digest refreshes are read from
the existing recipe/lock owners, not a second update configuration. FINite uses
exactly the recipe's Bluefin digest; FINite Dev uses its Bluefin DX digest.
Publisher verification runs before construction for Bluefin, Cosign and the
retained BlueBuild runtime binary. Foundation/Nix payload staging is unchanged.

| Responsibility | Experimental implementation |
| --- | --- |
| Users, groups and Nix RPM ordering | Existing `nix-identities.sh` before DNF |
| RPMs and repositories | Read from shared recipe; weak dependencies enabled |
| Security fixes and Tailscale | Existing remediation scripts |
| Foundation catalog and first login | Same staged files, service enablement and profile script |
| Determinate Nix seed, persistent mounts, SELinux and socket ordering | Existing `nix-install.sh`, assets and finalizer |
| PAM, FIDO2 and authentication | Existing `authselect.sh`, assets and finalizer |
| Kernel provenance and initramfs | Existing snapshot/verification around reproducible, non-host-only dracut |
| OS metadata and signed-rebase policy | Recipe properties, same public key and repository-specific verification policy |
| Runtime command availability | Same locked Cosign and BlueBuild binaries; CLI is not the builder |
| Mutable-directory cleanup and image checks | BlueBuild-compatible `/opt`/`/var` cleanup, existing `verify-image.sh` |

BlueBuild modules and Nushell are not executed in this alternative. The plain
builder therefore takes ownership of DNF, file copying, unit enablement,
initramfs invocation, policy configuration and cleanup behavior that BlueBuild
currently maintains. It adds maintained code; fewer builder dependencies alone
are **not** evidence of less total complexity. The contract snapshot is a review
alarm, not a second desired-state recipe or proof of runtime parity.

## Identity is deliberately different

The plan retains the production input identity as `referenceIdentity` only.
The actual `io.finite.build-inputs` label uses a distinct `containerfile-v1:`
namespace hashing that reference and the experimental implementation/workflow.
Revision, base digest, base name, profile and foundation labels are checked after
assembly. OCI URL/description are derived from the recipe, with an explicit
unpublished description and `containerfile-<head>` version; creation time is the
experiment preparation time, not inherited Bluefin metadata.
`io.finite.production-eligible=false` prevents any suggestion of a
qualified production result. The installed signed-rebase policy remains intact,
but that does not sign the experimental image. Production signing is unchanged.

## Validation and execution

The normal Nix bluebuild contract check and a small PR workflow run the unit
contracts without creating an image (the PR-specific opt-in below is separate).
Locally, with Python and PyYAML installed:

```sh
python3 experiments/containerfile/prepare.py
python3 tests/ci/containerfile-experiment.py
bash -n experiments/containerfile/build.sh
```

A temporary reviewed opt-in also enables full assembly **only for internal PR
#321 from `closure-labs/finite:codex/explore-containerfile`**. The event payload,
repository, non-fork status, base, PR number, branch and exact checked-out head SHA
are checked before assembly. Superseded experiment runs cancel; the two profiles
remain sequential and bounded to 120 minutes each. The build context is an
allowlist of image files, experiment files, public key, plan and verifier; `.git`,
credentials and unrelated runner files are not sent to Docker. Remove this
PR-specific trigger and its guard before any eventual main merge. This temporary
opt-in is necessary because GitHub does not expose dispatch for this branch-only
workflow; it is not a production or general PR build policy.

Otherwise, full image assembly requires an explicit `workflow_dispatch` of
`containerfile-experiment.yml` on an experimental branch, with `build_images`
set to true. It builds the two profiles sequentially, uses Docker `--load` only,
runs the existing image contract verifier with networking disabled, and uploads
plans, publisher-verification evidence, image inspection, build metadata and an
offline final RPM inventory. Its sorted NEVRA/architecture records have a canonical
JSON SHA-256 and bind the exact local image ID, source revision and experiment
identity. This is actual installed-package evidence, not the inherited upstream
rechunk label; it does not itself prove equality to a production inventory.
GitHub may require a new dispatch workflow to exist on the default branch before
it can be invoked; opening a draft PR alone is not an image-build result. Do not
merge merely to obtain a benchmark or route through a production publisher.

An assembly pass would still leave fresh-install, upgrade, SELinux/socket boot
ordering and first-login validation unproven. Existing production gates remain
the authority; no physical-hardware retest or Home Manager rollback test is
introduced. A later decision should compare observed build logs, output/package
inventories and actual maintained code/dependency costs before any migration.

## Upstream implementation references

The cleanup lifecycle follows BlueBuild CLI v0.9.37 (commit
`513065f998825e2de59f2e51ad1647fd0666f652`); initramfs, signing policy and DNF
semantics were reviewed against BlueBuild modules commit
`997fc19d1528f47e7cded70aba5840a18b271e64`.
These are Apache-2.0 works; the copied signing policy and adapted lifecycle code
retain that license in `experiments/containerfile/LICENSE.bluebuild`.
Sources: [CLI](https://github.com/blue-build/cli),
[modules](https://github.com/blue-build/modules),
[bootc image building](https://bootc.dev/bootc/building/bootc-building-images.7.html).

## First assembly observation (not final qualification)

Both profiles assembled and passed the existing offline image verifier in
[run 40807467855](https://github.com/closure-labs/finite/actions/runs/40807467855)
at `bf508bba78cc1c5d4151c08bc9fe2f011e299421`. The customization RUN took about
85 seconds per profile, while local Docker export/load took about 212 seconds
for FINite and 417 seconds for FINite Dev. These are one-run observations of
this different output path, not a controlled comparison or production speedup.
The run exposed inherited OCI metadata needing explicit experiment overrides;
source CI also caught a hermetic fileset omission and a literal cleanup glob
warning. Later revisions correct those and retain a final RPM inventory; their
own hosted results must be checked separately. Assembly does not establish boot
parity or authorize replacing the production builder.

## Refreshed Foundation provenance

The refreshed trial reads the exact Foundation revision, NAR hash and source
metadata from the current lock and `sources/foundation.json`, rejecting disagreement.
After assembly it reads `/usr/share/finite/foundation-source.json` from the same
immutable local image used for verification, and requires exact metadata equality.
It also records the executable `/usr/bin/fzf` path, resolved path, byte hash and
owning RPM, checking that the owner is the inventoried `fzf` package. The offline
`installed-provenance.json` receipt binds these observations to image ID, source
revision and experimental identity. No services or user sessions are started;
Foundation preparation, Homebrew and fzf itself are not executed by this query.

Foundation's updated Bluefin aspect waits for upstream-owned default provisioning
and uses stock fzf rather than installing optional Brew CLI bundles. This receipt
proves installed metadata and RPM ownership only, **not** first-login, user-session
provisioning or boot parity. The production builder and upstream trust ownership
remain unchanged.

## Hosted unsigned boot parity

The internal PR-321 image jobs now also prepare the existing pinned VM tools and
run the unchanged local-image acceptance harness after assembly. A small adapter
revalidates the authorized PR head, checkout, immutable image ID, experimental
labels and installed Foundation receipt before handing that image to the harness.
Its receipt uses the actual checked-out head (not GitHub's synthetic PR merge
SHA). No production identity, registry push, private signing key or new workflow
permission is introduced. Explicit dispatch remains assembly-only.

This exercises the existing disposable fresh-install, Secure Boot, enforcing
SELinux, Nix/service ordering and first-login checks on GitHub-hosted runners.
The installer consumes an unsigned local OCI archive; the installed production
signed-rebase policy remains unchanged. This is not signed upgrade qualification,
production eligibility, a physical-hardware test or a Home Manager rollback test.
A `vm-result.json` binds exit status and elapsed time to the exact experiment;
existing sanitized `vm-local` evidence and per-profile timing records are retained
on failure as well as success. Raw guest credentials and VM disks remain outside
the uploaded paths, as in the existing harness. Assembly and VM timings must be
reported separately; comparing this job's total against assembly-only runs would
be misleading. A prepared patch or green offline fixtures are not a hosted pass.
A runner timeout/cancellation can prevent `vm-result.json` from being written;
missing or partial evidence is inconclusive, never a pass. The 120-minute job
limit remains in force and does not grant an automatic retry.
