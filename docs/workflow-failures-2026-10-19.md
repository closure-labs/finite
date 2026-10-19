# Workflow failure follow-up: 2026-10-19

This follow-up distinguishes infrastructure failures from VM qualification
failures. The earlier [build RCA](build-failure-2026-10-19.md) documents the
scheduled-consumer and Foundation predecessor fixes already on this branch.

## Inventory metadata transport

The [published-image audit](https://github.com/closure-labs/finite/actions/runs/39280961366)
verified the finite-dev image signature, then GitHub returned HTTP 502 while
listing the original build attempt's jobs. Inventory retrieval treated that
transport error as an evidence rejection and stopped before scanning.

Inventory metadata GETs now allow three total attempts, each bounded to 35
seconds, with two- and four-second backoffs. Retries cover HTTP 408, 429, 500,
502, 503 and 504 and process timeouts. Authentication failures, missing
resources, malformed JSON and invalid evidence still stop immediately. An
exhausted transport budget remains a failure; it never grants security clearance
or silently accepts unauthenticated inventory.

## Weekly lock refresh

The [scheduled updater](https://github.com/closure-labs/finite/actions/runs/39286660442)
updated flake.lock, then `devenv update` initialized the repository's default
SecretSpec configuration. That configuration selects the developer's local
pass provider. GitHub-hosted runners do not have pass, so the job exited before
updating devenv.lock or opening an update PR.

Hosted lock updates now explicitly select the github-actions provider and
ci-options profile, which contains only optional public CI switches. Local
updates retain the configured developer provider. No signing credentials or
developer cache credentials are needed to update public lock inputs.

## On-demand qualification diagnostics

The [finite experiment](https://github.com/closure-labs/finite/actions/runs/39284870338)
and [finite-dev experiment](https://github.com/closure-labs/finite/actions/runs/39284875100)
were manually dispatched through the image-tools benchmark workflow with
`validation=qualification`. They were not scheduled benchmarks. All six
benchmark workflows remain on demand; the cache benchmark also supports a
reusable workflow call. Daily production builds and security audits retain
their schedules.

Both upgrade phases progressed past Foundation initialization, image transfer
and reboot. Retained updated-boot receipts show passing Secure Boot, encryption,
desktop/security and kernel checks. The retained bootc references and manifest
digests match the requested candidates. Both then failed before rollback in the
post-upgrade persistence checks. The original checks exited silently, and the
artifacts do not identify which preserved marker failed. These runs therefore
do not prove that upgrade/rollback qualification succeeds.

The persistence check now emits a bounded JSON receipt with separate Nix-state
and Home Manager customization outcomes, plus named errors without file
contents. Nix daemon persistence has its own retained log and named failure.
The original marker checks and required rollback remain enforced. These
diagnostics identified the fixture defect described below.

### Named preservation result and fixture correction

The [corrected finite diagnostic](https://github.com/closure-labs/finite/actions/runs/39293376758)
passed fresh qualification. Its upgrade receipt and the
[finite-dev upgrade receipt](https://github.com/closure-labs/finite/actions/runs/39293381163)
both report `nixState: true` and `homeCustomization: false`: the generated
customization file is readable, but the acceptance marker is absent. The
finite-dev fresh phase was still running when its upgrade receipt arrived.
This establishes the failed contract; it does not establish that an OS update
deleted an existing marker.

The fixture appended that marker after `home-init` inside the same SSH
`bash -s` script. Foundation and its child processes inherit that script's
standard input. A local regression demonstrates a child consuming the trailing
marker command while the parent shell exits successfully. The historical
predecessor fixture already contained the same marker, masking this gap; the
Foundation fixture correctly avoids precreating its configuration directory.
Inherited stdin is the leading explanation, rather than proven OS data loss.

`home-init` now receives `/dev/null` as stdin. A separate SSH request then
requires the generated configuration files, appends the acceptance marker, and
writes a successful initialization receipt before any upgrade starts. The
post-upgrade checks and required rollback remain enforced. The corrected
[finite run](https://github.com/closure-labs/finite/actions/runs/39298020638) and
[finite-dev run](https://github.com/closure-labs/finite/actions/runs/39298023824)
both pass fresh installation and upgrade. Their initialization and post-upgrade
receipts confirm both persistence markers, and rollback boots the predecessor
without a staged or queued update. This supports the inherited-stdin fixture
explanation rather than customization loss during upgrade.

## CodeQL workflow bootstrap

The [initial CodeQL run](https://github.com/closure-labs/finite/actions/runs/39289903156)
failed at startup without creating jobs. Its generated template referenced action
version tags, while this repository requires full commit pins. The companion
[CI run](https://github.com/closure-labs/finite/actions/runs/39289901233)
also rejected those unpinned references. The corrected workflow pins checkout,
CodeQL and Community Harden Runner, and the checked/live action allowlists match.
Python and Actions run without a project compilation step. The detached Go helper
has no Go module/autobuild target and retains its existing dedicated tests.

A subsequent CI run caught the repository-security fixture still describing the
old action allowlist. Both positive and drift fixtures now include the explicitly
allowed pins; wildcard/extra-action negative checks remain intact. Both CodeQL
languages and the corrected PR's hosted Nix/runtime checks pass; full image
validation is a separate check.

## Full native SBOM exceeds the inline attestation limit

The [first full build after the decision-controller merge](https://github.com/closure-labs/finite/actions/runs/39303992535)
completed both native security scans successfully. Both following SBOM attestation
jobs failed with `SBOM file exceeds maximum allowed size: 16777216 bytes`.
The CI gate correctly stopped publication when the required attestation failed.
This was an attestation transport limit, not a vulnerability rejection or scanner
failure.

The authenticated native SPDX documents are already compact: finite contains
4,945 packages in 94,127,612 bytes, and finite-dev contains 7,492 packages in
127,756,096 bytes. Whitespace removal saves only one byte per file. Dropping
packages or file evidence to meet GitHub's 16 MiB inline limit would weaken the
SBOM and does not address the underlying mismatch.

The remediation retains GitHub's build-provenance attestation and stores each
unchanged, full native SPDX document as an OCI artifact referring to the exact
image digest. A small, versioned signed SBOM-reference predicate binds the image,
profile, platform, full document SHA256/size and immutable OCI manifest digest.
The helper checks the registry manifest subject and native document layer before
signing that reference. Native inventory hashes and scanner coverage remain
unchanged. Consumers resolve and verify the referenced full SPDX document; this
is explicitly an external SBOM binding, not an inline SPDX attestation.

Resumed candidates also retain their original build provenance. Only a fresh
current-run build at the verified source revision creates a new build claim;
resuming an earlier digest, even from the same SHA, verifies existing provenance
against the original source digest, main ref, reusable signer and hosted runner.
A candidate without valid original provenance requires a fresh build.

## CodeQL finding review

All six open CodeQL alerts from the main scan at
`de2a04bc47be8280fc40f62cd8ec75dda3bb9a54` concern intentional fixture writes
in `EncryptedVmConsole` in tests/bluebuild/reliability.py. Its key is the public,
fixed sentinel `b'a1' * 32`, created in a temporary directory and never loaded
from credentials or used to protect real data. Each alert was considered
individually and dismissed as **used in tests**:

| Alert | Fixture purpose | Protection asserted |
| --- | --- | --- |
| [2](https://github.com/closure-labs/finite/security/code-scanning/2) | Seed logs and nested diagnostics with the sentinel | Every retained file is redacted; unrelated JSON is preserved |
| [3](https://github.com/closure-labs/finite/security/code-scanning/3) | Seed raw diagnostics before simulated redactor failures | Neither an exception nor an incomplete redaction creates an export directory |
| [4](https://github.com/closure-labs/finite/security/code-scanning/4) | Seed raw diagnostics before a successful export | Only sanitized diagnostics are exported |
| [5](https://github.com/closure-labs/finite/security/code-scanning/5) | Seed a synthetic SSH key file | The key file is excluded from exported diagnostics |
| [6](https://github.com/closure-labs/finite/security/code-scanning/6) | Seed a synthetic installer configuration | The installer configuration is excluded from exported diagnostics |
| [7](https://github.com/closure-labs/finite/security/code-scanning/7) | Seed a synthetic disk image | The disk image is excluded from exported diagnostics |

These dismissals do not suppress the CodeQL rule or alter production handling.
The production exporter redacts permitted diagnostics, rechecks for the key
before creating an export directory, and excludes key, installer and disk files.
The deliberately unredacted fixture inputs preserve regression coverage of
these boundaries.

## Validation

Focused fixtures cover transport recovery and retry exhaustion, permanent API
failures, malformed responses, authenticated inventory handling, hosted/local
updater arguments, manual-only benchmark triggers, and missing/changed VM
persistence markers. Shell syntax and ShellCheck pass for the modified shell
sources. Tests use installed tools; no full local Nix evaluation or image build
was performed. Both corrected hosted diagnostics pass fresh installation,
upgrade, persistence and rollback checks.
