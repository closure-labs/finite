# CI and publication implementation

The pipeline retains native Grype/Syft image coverage, signed Bluefin provenance,
Cosign signatures, fresh-install and upgrade/rollback qualification, authenticated
inventory reuse, and the daily full rebuild. Floating DNF/BlueBuild inputs are not
completely represented by the Nix graph, so a passing source-input comparison is
not a reason to remove daily builds.

Changes limited to the reviewed proposal workflow, decision controller entrypoint
and module, or admission module retain source and Nix/runtime contract checks
without rebuilding OS images. Mixed payload changes and unknown helpers remain
conservative; scheduled and manual full builds still select both profiles.

Full native SPDX SBOMs are retained as immutable OCI referrers. A signed
[SBOM-reference predicate](automation/sbom-reference-v1.md) binds each full
document's hash and size to the exact image; this avoids GitHub's 16 MiB inline
SBOM limit without dropping packages or file evidence. Build provenance remains
independently attested.

CodeQL scans Python and Actions. Nix and shell retain their existing dedicated
checks. StepSecurity Harden Runner runs in Community audit mode on GitHub-hosted
build, scan, attestation and signing jobs. Neither integration decides whether a
vulnerability is acceptable. Harden Runner's upstream global blocklist still
blocks known malicious destinations in audit mode; no custom egress allowlist
or paid policy feature is configured. Community does not include StepSecurity GitHub Checks,
workflow run policies, or Actions governance. No subscription or trial is needed.

Dependabot remains the dependency updater. This repository currently uses its
GitHub Actions ecosystem, grouped updates, cooldowns, and composite-action
discovery. Renovate does not provide enough additional value here to justify a
second updater. Foundation and Bluefin keep their provenance-aware updaters.
Cloudflare deployment/runtime controls do not replace source, dependency, or
native image scanning.

## Human decisions

The default-branch App controller creates bot-authored review PRs. The complete
security proposal includes both profiles, all severities including Unknown,
normalized CVE/component/exposure records, risk ceilings, and an immutable GHCR
packet. Review summaries link vulnerabilities; the full packet contains native
reports and authenticated producer identities and hashes.

Only a current human member of `closure-labs/super-admins` (team ID `20196962`)
with effective maintain/admin access may approve the exact PR head. The App-origin `Maintainer decision authority` check verifies current role,
review state, live pinned-team membership, immutable proposal content and merge provenance. It also protects
changes to the verifier and privileged workflow controls. Labels, PR comments,
self-reported approvers, AI `reviewedBy` fields, publisher provenance and merged
JSON alone cannot grant authority. Loss of team membership, a push, dismissed review or unresolved eligible
changes-requested review prevents admission. Merge queue content must match the
approved governed content even though its synthetic SHA differs.

Accepted risk has no renewal timer. Same CVE/component/profile risk may carry
across package versions and image digests when severity, CVSS, exploitation and
exposure stay the same or improve. New/worsened risk requires another decision;
new fix availability alone does not. Components without a stable package URL are
bound to an exact image digest. Missing coverage, malformed evidence, stale
current scanner databases and API failures cannot be accepted as vulnerability
risk. Scanner completion and admission remain separate states.

Supersession is explicit. Revocation blocks future publication; it does not
withdraw published releases. Only the active leaf needs current human authority;
superseded records retain immutable bot merge provenance so a new authorized
maintainer can reaffirm a decision after an earlier reviewer's departure.

## Official versions

One release-set proposal covers finite and finite-dev for a version, while the
existing `finite-VERSION` and `finite-dev-VERSION` release pages remain separate.
Both qualified ISOs and immutable core asset hashes are prepared before approval.
Large ISOs split into deterministic GitHub-sized parts before their approval
identity is calculated. Refreshed scan/signature evidence remains outside the
immutable product identity. New unresolved findings wait for a separate security
decision rather than repeating release approval for unchanged product bytes.

Publication rechecks authority and admission before credentials and before
publishing. Its durable journal uses a payload identity and compare-and-swap
updates, reserves versions, and reconciles existing exact tags/assets. It never
retargets a tag or overwrites a mismatched asset. Both drafts are staged before
either is published. GitHub cannot atomically publish two releases: a partial
outcome is recorded and resumed without pretending both succeeded.

## Bootstrap and cutover

CL Decider is installed, its App-bound required check is live, and Super Admins
membership verification has passed against the private team. The initial
both-profile baseline was approved and merged in
[PR 188](https://github.com/closure-labs/finite/pull/188).
[PR 191](https://github.com/closure-labs/finite/pull/191) tracks the separately
reviewed activation of `maintainer-decision` mode. Its CI correction gives
historical policy tests an explicit legacy fixture; the complete 1,072-test
CI/BlueBuild matrix passes in both legacy and maintainer modes.

The release environment reviewer remains restricted to Super Admins during the
release transition. Package-cleanup review also uses that team. The sequence
below records the activation and verification boundaries.

Initial baseline proposals use the same native severity and CVSS calculations as
the eventual maintainer mode. Legacy AI dispositions cannot suppress those
observations, and preparing a proposal does not change publication enforcement
or grant human approval.

1. Install the repository-scoped App and configure its public IDs/bot login and
   SecretSpec private key. Grant Organization Members read and approve the
   installation update; verify the pinned Super Admins team. Keep the existing audit App read-only.
2. Exercise authority checks on ordinary PRs, exact-head reviews, stale/dismissed
   reviews, forged proposals and merge queue commits. Add the required check with
   this App's integration ID to live main protection and both checked ruleset
   policies. The proposer refuses to autoqueue before this binding exists.
3. Compare complete scan observations with existing enforcement. Merge an explicit
   human-approved initial baseline covering both profiles. Existing AI reviews and
   publisher authentication are not grandfathered into that baseline.
4. In a separately reviewed cutover PR, change image policy to `maintainer-decision`
   with only native-health fields and confirm both profiles can independently
   verify `covered` admission before signing/promotion. Run the new two-image
   release path and its retained-evidence recovery checks.
5. Update checked repository policy and live release environment together to
   remove its repeated human reviewer, retaining main-only credential access.
   Cancel superseded publication runs. Old release paths must not bypass the
   unified decision path; retire their entrypoints when cutover is complete.

The mode's native-health fields are schema, mode, maxDatabaseAgeHours,
maxEvidenceAgeHours, distributionAliases, requiredReleasePackage,
minimumRpmPackages, requiredProviders, and coverageProbePackage. Remove obsolete
AI review/exception fields when constructing that cutover policy. Activation must
fail closed if the App, baseline, or verifier is unavailable.

The decision coordinator resumes retained candidates after approval, with fresh
scans when evidence expires. Its hourly health check maintains one issue for an
audit missing more than 36 hours or a human decision pending more than 72 hours.
Neither timeout approves nor rejects risk. All diagnostic/cache benchmarks remain
on demand. New caches require three comparable measurements before activation.
The decision packet GHCR package is separate from existing image/ISO cleanup;
referenced packet digests must be retained permanently.

## Verification

Focused tests cover risk carryover, new/worsened/unknown findings, empty initial
baselines, scanner failures, forged/stale/dismissed approvals, role changes,
supersession/revocation, exact queue content, packet integrity, release retries
and immutable assets. Hosted CI supplies full Nix checks. Local verification uses
installed Python/shell/lint tools to avoid the documented workstation Nix OOM.
