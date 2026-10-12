# Security audit implementation

User authorized implementation of the 2026-10-12 cybersecurity report using
great_cto and nixos-managing. Existing product choices remain: personal daily
driver, automated qualified images, manual application updates, opt-in raw
keyboard access, shared read-only audit App, and Jujutsu repository workflow.
Beads is unavailable; this file is the skill's task-tracking fallback.

| Phase | Owner | State | Completion evidence |
| --- | --- | --- | --- |
| Scope and architecture | root + security-officer | Approved by implementation request | Implement report treatments; isolate signer; preserve immutable qualification |
| R1/R6 publication controls | security_delivery | Implemented | Digest-bound scan policy and isolated signer |
| R2 live settings audit | security_settings | Validated: full CLI + partial App | Complete normalized settings and negative fixtures |
| R3/R4 runtime controls | security_runtime | Implemented | SELinux reconciliation and cloud-init disabled by default |
| R5 upstream trust | root | Implemented | Reviewed publisher key and negative signature tests |
| Integration and documentation | root | Implemented; hosted contracts pass | Pinned Nix checks, runbook and residual requirements |
| Independent code/QA/security review | specialists | Approved | No blocking source findings; focused suites passed |
| Hosted validation and deployment | root | Image validation pending; current image blocked by policy | PR #139; CLI/App audits, hosted Nix/runtime checks and native extraction preflight pass; real native inventory + authenticated Grype continuation find 281 unique fixable High/Critical component/advisory pairs |

Operational constraint: after workstation memory pressure, stop local Nix evaluations,
image scans and VM builds. Use hosted runners for remaining full validation.
Existing signing key migrated into image-signing and release environment secrets;
repository copy retirement remains pending old-workflow completion.

## Follow-up PR: scan remediation and CI tool reuse

User requested a new PR with Nix CI optimizations and the latest failed scan's
remediation. Work is isolated in Jujutsu workspace `security-remediation`, based
on PR #139; its existing change remains intact.

- Reuse pinned image tools once per job and use lightweight maintenance exports.
- Apply reviewed fixed-version floors to installed Fedora RPM packages only.
- Preserve all 281 component/advisory pairs in the remediation ledger.
- Keep Go, kernel, AnyIO and other unresolved findings blocked until rescanned.
- Run hosted cold/warm tool benchmarks and image validation before merge; local
  tests establish orchestration behavior only. No local Nix builds or image scans.

## Validation/remediation execution

- Planning: documented staged validation and acceptance criteria in
  `docs/validation-remediation-plan.md`; user explicitly authorized implementation.
- Performance QA: two hosted cold/warm benchmark pairs passed with lower setup
  time; artifact retention verified on second run. No more repeats needed.
- Security prerequisites: all 16 implemented RPM floors available, ownership
  mapped from the existing authenticated SBOM. AnyIO/msgpack/rclone fixes remain
  unavailable; explicit readiness probe correctly reports blocked, not error.
- CI remediation: cancelled doomed PR140 matrix after shared RPM parser rejected
  legitimate `gpg-pubkey` architecture `(none)`; exact exception and regression
  fixtures implemented. Validate actual transaction on one authenticated base
  container before restarting the full matrix.
- Independent QA/security: new prerequisite/ownership/diff helpers reviewed;
  summary comparisons are triage-only and never automatically resolve findings.
- Release remains blocked by unavailable owning-package fixes and unverified
  remaining Go/kernel findings. No broad suppressions or package overlays added.
- Focused transaction: run 38295423922 passed on the authenticated Bluefin base,
  including actual fixed-floor transaction and already-satisfied second run.
  Ready to resume the final PR matrix; upstream scan-readiness remains blocked.
