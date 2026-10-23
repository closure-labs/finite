# Reports and project history

Use [CI and releases](ci-and-releases.md) and [security review](security-review.md)
for operating instructions. These reports retain the evidence and decisions
behind changes. Run IDs, profile names, counts and policy descriptions refer to
the recorded revision and date.

## Incidents and current implementation

| Record | Scope |
| --- | --- |
| [CI stage rollout, October 23](ci-stage-rollout-2026-10-23.md) | Split guest intervals, corrected queue receipt joins and incomplete main cohorts |
| [CI follow-through, October 23](ci-follow-through-2026-10-23.md) | Complete queue/main timings, authenticated two-profile promotion and hosted health after #237 |
| [ISO transfers, October 23](iso-transport-2026-10-23.md) | Initial queue timings, a failed predecessor transfer and the remaining release-packet duplication |
| [Payload evaluation, October 23](ci-payload-evaluation-2026-10-23.md) | Pre-build timeout and an equivalent direct payload entry |
| [Predecessor ISO reuse, October 23](ci-predecessor-2026-10-23.md) | A confirmed context mismatch and authenticated restore observations |
| [CI rollout and governed dependency updates, October 23](ci-rollout-2026-10-23.md) | Verified production qualification, VM stage measurements and Dependabot submitter diagnosis |
| [Workflow architecture, October 23](ci-architecture-2026-10-23.md) | PR/queue duplication, installer cost and Nix/devenv evaluation boundaries |
| [Workflow failures, October 19](workflow-failures-2026-10-19.md) | Inventory transport, lock refresh, VM fixtures, CodeQL and SBOM attestation |
| [Build RCA, October 19](build-failure-2026-10-19.md) | Scheduled workflow consumers and Foundation predecessor initialization |
| [Maintainer decision implementation](ci-maintainer-decisions.md) | Architecture, approval rules, rollout status and verification |

## Releases and measurements

| Record | Scope |
| --- | --- |
| [v0.8.1 release results](v0.8.1-release-results.md) | Published two-channel releases, signed assets and qualification receipts |
| [v0.8.1 preparation](v0.8.1-release-plan.md) | Version and profile-name transition |
| [October 15 reuse results](new-os-reuse-results.md) | Two-profile measurements, activation receipt and rollback settings |
| [Reuse experiment design](reuse-timing-experiments.md) | Comparable inventory, database and VM measurements |
| [v0.8 release results](v0.8-release-results.md) | Earlier release evidence |
| [v0.8 execution plan](v0.8-release-plan.md) and [hosted pilot](v0.8-hosted-pilot-results.md) | Earlier four-profile release and cache experiments |
| [October 14 rollout results](ci-rollout-results.md) | Hosted qualification and cache measurements |
| [CI optimization review](ci-optimization-review.md) and [rollout plan](ci-rollout.md) | Measured bottlenecks and the earlier rollout |
| [Nix workflow resources](nix-workflow-resources.md) | Runner sizing and concurrency audit |

## Earlier security and migration work

The October 12–13 records describe policies and profile layouts used at the
time. Read them alongside their original source revisions and evidence hashes.
The checked-in policy and authenticated maintainer decisions govern publication.

- [Security assessment](security-audit-2026-10-12.md),
  [implementation record](security-implementation.md) and
  [scan remediation](security-remediation-2026-10-12.md).
- [Desktop risk analysis](desktop-risk-policy.md),
  [Critical remediation](critical-desktop-remediation.md) and
  [release qualification policy history](desktop-release-qualification.md).
- [Security validation](desktop-security-validation-plan.md),
  [kernel remediation](generic-kernel-remediation-plan.md) and
  [validation continuation](validation-remediation-plan.md).
- [Release eligibility sequence](release-eligibility-sequence.md) and
  [implementation sequence](release-implementation-sequence.md).
- [Doppler OIDC assessment](doppler-oidc-assessment-2026-10-13.md) and
  [canary pilot setup](doppler-pilot-setup.md).
- [Early BlueBuild sandbox validation](bluebuild/baseline-validation.md) and
  [qualification recovery history](bluebuild/qualification-recovery-history.md).

Companion JSON files preserve machine-readable evidence. Files named
`current-*-2026-10-12.json` or `current-*-2026-10-13.json` are snapshots from
those dates. Their image digests, producer revisions and hashes define their
scope. The Markdown reports link to the relevant receipts and source records.
