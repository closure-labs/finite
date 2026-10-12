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
