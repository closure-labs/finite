# CI and releases

BlueBuild builds the four recipes against Bluefin and Bluefin DX `stable`
channels. Each profile publishes independently to `ghcr.io/closure-labs/finite`.

## Build and validate

[Build Finite](https://github.com/closure-labs/finite/actions/workflows/build.yml)
runs on pull requests, merge groups, main pushes, daily schedules and manual
dispatches. It selects work from the complete Git diff for each event:

| Changed inputs | Required work |
| --- | --- |
| README, changelog, license or `docs/` only | Text style and local Markdown links |
| Tests, automation, devenv lock or installer/dependency workflows | Documentation and Nix/runtime checks |
| Nix modules, Home Manager, flake lock or version | Documentation, Nix/runtime checks and images whose payload derivation changed |
| One recipe | Checks and that recipe's image |
| Shared next-kernel recipe or kernel script | Checks and both next-kernel images |
| Shared system files, signing, build CI or other paths | Checks and all four images |
| Daily schedule or manual dispatch | All checks and all four images |

Fast checks finish before image builds start. A documentation-only main push
runs documentation checks; the daily schedule refreshes upstream inputs.
Missing comparison data selects full validation. Renames include both paths,
so moving an image input into documentation still triggers image builds.

For Nix changes, CI evaluates `image-payload.drvPath` and
`image-payload-next.drvPath` at the base revision and the actual checked-out
PR, merge-queue or main revision. These identities include their declared Nix
dependencies. Matching identities skip the corresponding image rebuilds;
changed identities select the two generic or two next
profiles. Evaluation uses the committed lock file and records both identities
in the job summary. It evaluates the dependency graph without building payloads.

The Nix comparison adds to images selected by recipe and system-file changes.
An evaluation failure selects all four images. The daily full build also
checks upstream Bluefin and BlueBuild inputs outside Nix's dependency graph.

The required `CI gate` runs for every event. It requires success from selected
jobs and verifies that other jobs were explicitly skipped. Failures,
cancellations and missing selection outputs block merging. Merge-queue checks
use the queue's base and proposed merge revisions.

| Run | Registry permissions | Signing |
| --- | --- | --- |
| Pull request or merge group | Read | Public key available for policy assembly |
| Trusted main build | Write | `COSIGN_PRIVATE_KEY` supplies the signing key |

Both paths use the same Docker builder and pinned BlueBuild Action v1.12.0
(`836161eb076426a451e6a0054f722b1153b8b3ad`) with CLI v0.9.37. Publication runs
serialize; successful profiles publish their own channel tags. The upstream
action manages building, caching, pushing and signing.

The builder's `default-load=true` setting makes validation images available for
inspection. The final-image step runs after upstream cleanup and checks the
Nix seed, packages, profile, signing policy, kernel and `bootc container lint`.

Each profile's evidence artifact contains its image reference, labels, generated
Containerfile and signature verification. The final image's base-digest label
records the actual Bluefin input. Its source revision identifies the Finite
commit that was built.

## Image signing

`cosign.pub` is the public trust key. The matching private key belongs in the
repository's `COSIGN_PRIVATE_KEY` Actions secret. Verify a published digest from
a trusted checkout:

```bash
cosign verify --key cosign.pub IMAGE_REFERENCE
```

The image configures signature verification for `ghcr.io/closure-labs/finite`
with these files:

| File | Purpose |
| --- | --- |
| `/etc/pki/containers/finite.pub` | Finite public key |
| `/etc/containers/policy.json` | `sigstoreSigned` policy with `matchRepository` identity |
| `/etc/containers/registries.d/closure-labs-finite.yaml` | Enables Sigstore attachments for the repository |

When preparing an existing workstation for a new key, verify the published
image with the reviewed public key, install that key, and update the Finite
entry in the container policy and registry configuration. Preserve the
existing policies for other registries. Then use
`bootc switch --enforce-container-sigpolicy` and review the staged deployment
before rebooting.

Generate replacement key pairs in a private directory outside the source
checkout. Upload the private half with
`gh secret set COSIGN_PRIVATE_KEY --repo closure-labs/finite < cosign.key`
and commit the public half. Validate the resulting image and host policy as
part of key rotation.

## Publish a release

1. Update `VERSION` and add a dated entry to `CHANGELOG.md` in a PR. The version
   also identifies the staged Home Manager template.
2. Pass `CI gate` and merge through the queue. Wait for all four signed main
   image builds and their final-image checks to succeed.
3. Record the successful build revision and each profile's digest. Create the
   `vVERSION` Git tag at that exact revision, then publish the GitHub release
   with the changelog notes and image evidence.
4. Use the [ISO workflow](installation.md#get-an-iso) for any requested installer
   artifacts, and validate them with the [hosted VM test](development.md#validate-an-iso).

The channel tags continue to receive daily builds. Release records identify
specific source revisions and image digests for reproducibility.

## Maintain dependencies and repository policy

Nix lock updates, coordinated Home Manager/Nixpkgs release updates and the
Determinate checksum update use the retained dependency workflows. Their
protected-branch automation uses `MERGE_QUEUE_TOKEN`.

The checked-in policy at `automation/github/repository-security.json` describes
the action allowlist, SHA pinning, default read-only token and repository
security settings. Audit the live repository from a checkout with GitHub CLI
access:

```bash
nix run --accept-flake-config .#repository-security-audit
```

## Update reliability and measurement

Source lookups use at most four GET attempts, with a 30-second attempt timeout,
10-second socket timeout and 150-second total retry budget. Retry delays start
at 2, 4 and 8 seconds; a larger `Retry-After` is honored only if it fits within
the budget. Authentication, permission and malformed-release errors fail without
retrying. Missing future branches or HTTP 404 mirrors report no change; outages
fail the update. Existing Determinate pins are replaced only after complete,
nonempty asset downloads and metadata validation.

Lock generation preserves file content and appends a missing final newline
before computing change outputs. Generated updates pass text checks before a
PR is created. Dedicated credentials remain scoped to existing PR/merge steps;
the default workflow token has contents-read permission.

Updater jobs allow 210 minutes, including a bounded 180-minute wait for child
validation. Existing PR and manual runs are reused only for the same branch
and commit. Failures include a direct run link and never enable auto-merge.
A fresh dispatch after integration uses the corrected workflow; rerunning an
older run uses its older revision.

The [CI optimization review](ci-optimization-review.md) records the 30-day
baseline, confirmed causes, current bottlenecks and ranked follow-up work.
