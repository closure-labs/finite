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
The original marker checks and required rollback remain enforced. A new hosted
diagnostic run is required to identify and remediate the remaining VM failure;
the added diagnostics are not a claim that its underlying cause is fixed.

## Validation

Focused fixtures cover transport recovery and retry exhaustion, permanent API
failures, malformed responses, authenticated inventory handling, hosted/local
updater arguments, manual-only benchmark triggers, and missing/changed VM
persistence markers. Shell syntax and ShellCheck pass for the modified shell
sources. Tests use installed tools; no full local Nix evaluation or image build
was performed. Hosted reruns remain necessary after these changes are pushed.
