# Cybersecurity assessment: 12 October 2026

Finite has useful supply-chain and release controls, but the passing repository
settings audit is not a comprehensive security clearance. This assessment found
two reproducible implementation defects, a vulnerability-management coverage
gap, and additional trust-boundary risks. No credential leak or remotely
exploitable application vulnerability was confirmed.

## Scope and method

The assessed source is commit
`74e36abd72f52b1e20c9fda3268de5c3bfeaa29b`, submitted in
[PR 138](https://github.com/closure-labs/finite/pull/138). Its parent main revision
is `2b992783`. This is a Jujutsu repository colocated with Git. The report lives
in a separate local Jujutsu change; it does not modify the submitted implementation.

Reviewed areas: GitHub Actions and live repository settings; credential scopes;
image building, signing, qualification and promotion; dependency updates and
SBOM coverage; installer and cloud-init configuration; SELinux/Nix lifecycle;
privileged helpers; Home Manager, Brew and Flatpak updates; diagnostic artifacts;
and security regression tests. The objective is protection of a personal daily
driver and its software distribution pipeline over the next 90 days.

Applied cybersecurity skills:

- `conducting-cyber-risk-assessment-with-nist-800-30`: system boundaries,
  threat events, likelihood/impact, evidence and treatment priorities.
- `analyzing-sbom-for-supply-chain-vulnerabilities`: component inventory,
  package identification, historical SBOM analysis and coverage limitations.
- `building-vulnerability-scanning-workflow`: finding triage, proposed
  remediation deadlines and verification criteria.

This is a source/configuration assessment with static scans and safe local
reproductions. It is not a certification or a live workstation penetration test.
No physical machine, current assembled image, firmware, installed browser,
listening services or actual user data was inspected. Organization-wide App
installation scope, MFA, membership and organization secret access policies
could not be inspected with the available CLI permissions. The audit App's
successful hosted token generation was verified separately.

Risk uses the skill's five-level qualitative matrix. These are auditor-selected
ratings, not measured attack probabilities or CVSS scores. "Very High" impact
means potentially compromising distributed OS images or root-level workstation
integrity. Residual ratings below are targets pending implementation and retest,
not claims that mitigation has occurred.

Threat sources include a compromised maintainer or dependency publisher,
malicious local/removable provisioning media, accidental configuration drift,
failed update services, and storage/provider failures. Root-level malware and
data loss matter even when the project has only one primary user.

## Prioritized findings

| ID | Finding | Evidence status | Likelihood | Impact | Risk | Priority / proposed owner |
| --- | --- | --- | --- | --- | --- | --- |
| R1 | Daily image publication lacks a vulnerability policy gate | Confirmed control gap | Moderate | Very High | High | P1 / release maintainer |
| R2 | Repository audit misses environments and branch rules | Reproduced implementation defect | High | Moderate | Moderate | P1 / CI maintainer |
| R3 | Existing SELinux module prevents updated policy installation | Reproduced implementation defect | Moderate | High | Moderate | P1 / OS maintainer |
| R4 | NoCloud provisioning is a privileged input without an enforced narrow schema | Configuration risk; installed behavior untested | Low | Very High | Moderate | P1 validation / OS maintainer |
| R5 | Upstream digest updates lack an explicit publisher-signature check | Confirmed trust-control gap in Finite updater | Low | Very High | Moderate | P2 / supply-chain maintainer |
| R6 | Signing and automation credentials depend on repository-wide trust | Confirmed design exposure; no compromise observed | Low | Very High | Moderate | P2 / repository owner |

### R1: vulnerability evidence does not gate daily image publication

Evidence: [.github/workflows/release.yml](../.github/workflows/release.yml),
lines 52-65, and
[.github/workflows/publication.yml](../.github/workflows/publication.yml).
SBOM generation and Grype exist only in the manually dispatched draft-release
workflow. The scan has `continue-on-error: true` and no `--fail-on` threshold.
Daily public-channel promotion checks signatures, identity and boot acceptance,
but never consumes a vulnerability result. A scanner failure or vulnerable
dependency therefore cannot prevent routine image promotion. The scan status
correctly says `advisory`; successful execution does not mean zero vulnerabilities.

The latest published release, `v0.6.0`, lists image evidence and checksums but no
SBOM asset. A historical `v0.5.0` SBOM was available. Neither this fact nor an
empty Dependabot alert list establishes the vulnerability status of current
RPM, Nix, Brew or Flatpak software. Dependabot is configured for Actions updates.

Treatment: generate a digest-bound SBOM for every publication candidate; retain
scanner version, database age, distribution identity and match coverage. Make
scanner failure a distinct result. Gate on an agreed policy for applicable
known-exploited vulnerabilities and fixable high/critical findings, with reviewed,
expiring exceptions. Rescan published digests as advisories change. Inventory
post-login Nix, Brew and Flatpak software separately. Preserve manual app updates
while defining a security-patch response time.

Validation: inject a failing scanner, stale database and a policy-violating test
result; public tags must remain unchanged. A finding exception must expire and
apply only to the specified vulnerability/component/digest. Target residual: Low.

### R2: the settings audit can pass without inspecting critical settings

Evidence: [repository-security-audit.nix](../lib/ci-applications/repository-security-audit.nix),
line 104 assigns `environment_json='{}'`. The implementation does not request
rulesets or effective main-branch rules. Its comparison walks expected leaf
values; an empty expected object also fails to detect unexpected child objects.

Reproduction: added an `unexpected` environment and empty `rulesets` to the
passing snapshot fixture. The actual audit executable returned exit 0 with
`{"status":"pass","drift":[]}`. Read-only GitHub API inspection found two real
environments, `release` and `package-cleanup`, with reviewer and branch policies.
Their presence is not itself a vulnerability; representing them as empty is an
audit coverage defect. The live main ruleset currently has CI and a merge queue,
no bypass actors, and zero required independent approvals.

The earlier hosted App audit and the fresh CLI audit genuinely passed their
implemented checks. They cannot detect loss of branch protection, merge-queue
requirements or environment restrictions.

Treatment: explicitly model intended environments and effective branch rules,
fetch and normalize live values, compare complete relevant structures and fail
on unreadable required endpoints. Report inspected, excluded and unavailable
controls separately. Do not delete valid environments merely to match `{}`.

Validation: tests must detect deleted rules, weakened reviews, new bypass actors,
changed check integration IDs, missing/unexpected environments and API denial.
Target residual: Low.

### R3: updated SELinux policy is skipped on previously provisioned machines

Evidence: [install-determinate-nix-selinux-policy](../files/system/usr/libexec/finite/install-determinate-nix-selinux-policy),
lines 4-9, installs only if `semodule -l` does not contain a module named `nix`.
There is no comparison with the policy shipped by the new image.

Reproduction: ran the script with harmless command stubs representing an existing
`nix 1.0` module and a changed policy file. It exited 0 without invoking
`semodule -i`. Existing regression tests verify install-once behavior but do not
test replacement policy bytes. Actual persistence across an installed bootc
upgrade still needs VM verification; the script's skip decision is reproduced.

Impact: machines retaining their SELinux module store can miss security-policy
updates or encounter incorrect access rules after an upgrade. No specific
over-permissive rule or exploit in the current policy was established.

Treatment: reconcile the installed module against the image policy, including
rollback. Use an installed-policy digest/version plus robust reconciliation,
or idempotent installation when the shipped policy changes. Update any marker
only after a successful policy transaction and preserve home-context ordering.

Validation: exercise old-to-new policy, unchanged policy, failed installation,
missing module and rollback on a VM. Target residual: Low.

### R4: NoCloud is broader than the Finite profile generator

Evidence: [base recipe](../recipes/shared/base.yml) enables `cloud-init.target`;
[90-finite-nocloud.cfg](../files/system/etc/cloud/cloud.cfg.d/90-finite-nocloud.cfg)
permits NoCloud. [home-profile-applications.nix](../lib/home-profile-applications.nix)
generates a benign `cidata` seed containing a profile file, but that generator
does not constrain other cloud-init user-data. Defaults such as `users: []`,
`disable_root: true` and `ssh_pwauth: false` are not a profile-only validator.

Cloud-init supports NoCloud configuration from labeled local media and multiple
user-data formats. A party able to supply accepted provisioning data may exercise
the broader provisioning interface. Exact exposure depends on inherited module
configuration, datasource discovery, first-boot state and whether the system is
booted/unlocked. This is not a demonstrated remote attack or a claim that LUKS
can be bypassed.

Treatment: disable general-purpose cloud-init for ordinary desktop installs, or
make provisioning an explicit, time-bounded opt-in. Prefer importing only a
validated Finite profile from a trusted local source. If full cloud-init is
required, document it as administrator-equivalent provisioning and establish
source authentication and a post-provisioning disablement policy.

Validation: in a disposable installed VM, use harmless marker-file tests with
untrusted NoCloud media at first boot and after provisioning. Check effective
cloud-init configuration and verify that normal installations reject the media.
Target residual: Low, contingent on that test.

### R5: immutable upstream references are not publisher authentication

Evidence: [bluefin-upstream.py](../scripts/ci/bluefin-upstream.py), lines 84-110,
resolves the allowed registry's `stable` tag and validates digest/platform. It
does not verify an upstream signature before proposing the digest update.
The [Bluefin updater](../.github/workflows/update-bluefin.yml) can then validate
and enable auto-merge. Finite's later signature authenticates Finite's output;
it is not evidence that an upstream publisher signed the input.

There are also deliberately floating build inputs: BlueBuild modules use `@v1`,
RPMs are selected at build time, and Terra's bootstrap GPG key comes from the
repository's HTTPS endpoint. Signature checks are enabled for Terra packages
and metadata, which is useful, but the bootstrap key is not independently pinned.
No compromised upstream was observed. Hidden behavior inside upstream tools was
not established as a substitute for an explicit, tested Finite trust policy.

Treatment: verify supported upstream signatures against reviewed key or workflow
identities before accepting new digests, and record the result. Where no signed
identity is available, document the alternative trust decision. Record resolved
module digests and package provenance; pin bootstrap signing keys where feasible.
Keep timely security updates rather than freezing dependencies indefinitely.

Validation: reject an unsigned or wrong-signer upstream fixture before opening
an update PR; preserve existing pins on verification errors. Target residual: Low.

### R6: credential isolation stops at the repository trust boundary

Evidence: repository secret metadata includes `COSIGN_PRIVATE_KEY` and
`MERGE_QUEUE_TOKEN`. The live main ruleset requires no independent approving
review. Image publication has main-branch guards, but the signing key is supplied
to the image-build job. The existing GitHub `release` environment is not referenced
by the current release workflow, so its protections do not gate that workflow.
No secret values were retrieved or tested.

A compromised write-capable maintainer account or trusted build dependency can
have more impact than a malicious fork PR. Repository secrets are not restricted
to the main branch merely because the current workflow has a main-branch `if`.
The short-lived audit token is correctly restricted to Finite and Administration
read, but possession of the shared App private key permits minting other tokens
within the App's granted installation scope. Per-run token scoping does not
isolate the underlying reusable PEM between repositories.

Treatment: define a signing boundary, ideally a separate job with narrow inputs
and no untrusted build execution. Consider branch-restricted environment secrets
and review for changes to workflows, trust roots and signing policy. For a solo
maintainer, document the review tradeoff rather than inventing an unavailable
second reviewer. Restrict organization secret access to selected repositories;
use separate Apps for different trust tiers or keep key custody in a trusted
token broker. Reusing the audit App is compatible with this approach.

Validation: a branch outside the approved deployment policy must not obtain a
signing credential; inventory App permissions, installation repositories and key
rotation/revocation procedures. Do not test exfiltration. Target residual: Low.

## Checks and positive controls

| Check | Result and limit |
| --- | --- |
| Actionlint | No diagnostics across repository workflows |
| Zizmor 1.25.2, offline | No findings; offline mode does not assess live upstream advisory/reputation data |
| Gitleaks 8.30.1, local Git history | 689 local commits scanned; 79 matches, all verified as public-key SHA256 fingerprints in kernel policy files and Jujutsu conflict snapshots; no confirmed credential leaks |
| Bandit 1.9.4, `scripts/` | 48 raw findings: 46 low subprocess/path warnings, one medium URL warning and one high XML-RPC warning; no confirmed high-severity exploit after source triage |
| Regression checks rerun | 12 maintenance, 33 reliability, 4 delivery-policy and 7 HTTP-helper tests passed; SELinux lifecycle shell contracts passed |
| GitHub alerts | Dependabot and secret-scanning endpoints returned empty lists; these are not complete software vulnerability inventories |
| GitHub code scanning | API returned 404/no analysis; no successful code-scanning coverage claimed |
| Existing repository audit | Fresh live pass; limitations in R2 apply |

### SBOM scan results and interpretation

Scanned the published `finite-bluefin-generic-v0.5.0.spdx.json.gz`, generated
26 August 2026, with pinned Grype 0.112.0 and its valid database built
12 October 2026 at 06:45:22 UTC. The inventory contains 2,169 packages and 14,544
relationships, including 1,857 RPM package URLs. Grype produced 59 advisory
matches: 1 critical, 34 high, 20 medium and 4 low. These are raw historical
matches, not 59 confirmed exploitable vulnerabilities in current Finite.

The critical match is `anyio 4.13.0`, recorded by the SBOM from an installed
Python package manifest. The
[reviewed AnyIO advisory](https://github.com/advisories/GHSA-82r6-8w77-94w6)
confirms versions below 4.14.2 are affected by a TLS hostname-validation issue.
The SBOM's dependency graph connects AnyIO to `httpcore` and `httpx`, making
those consumers relevant to follow-up reachability checks.
Exploitation requires relevant internationalized hostnames and a redirected or
hijacked connection; this audit did not demonstrate that execution path in
Finite. Check the current digest and obtain vendor backport evidence before
deciding whether an installed version needs replacement. If unpatched, update
the owning package/image to a fixed build and rescan.

Treat the count cautiously: Grype explicitly failed Linux distribution detection,
reporting `bluefin` version `44` with `idLike: [bluefin]`, so RPM advisory matching
is incomplete. Of the 59 matches, 46 concern a PostgreSQL component from Qt's
embedded third-party SBOM. This is not proof of a running PostgreSQL server;
component and reachability triage is required. A source-directory Syft inventory found 55
components; it likewise is not an inventory of the built OS or applications
installed after login. Do not manually guess a distribution override merely to
produce a cleaner scan. Preserve correct Fedora identity/version and vendor
patch information in a fresh digest-bound SBOM.

The scanner output and database metadata are retained locally in
`/tmp/finite-cyber-audit/historical-grype.json` and `sbom-summary.json`.
Current public-channel vulnerability status remains unverified.

Bandit's XML-RPC warning concerns the fixed Fedora Koji HTTPS endpoint in
`kernel-update.py`; parsing is bounded to a 4 MiB response and a network timeout.
It remains worth hardening XML parsing and redirect policy, but the scanner's
generic rating alone is not evidence of an exploitable high-severity flaw.
The subprocess calls reviewed use argument lists rather than `shell=True`.

Positive controls include full-SHA Action pins, read-only default workflow
permissions, checkout credential persistence disabled, no untrusted
`pull_request_target` execution in the reviewed workflows, explicit publication
guards, protected merge queue, immutable image references, signature verification,
digest-bound qualification, Secure Boot/LUKS acceptance requirements, negative
signature tests, and fail-closed artifact export. VM credentials and disks remain
outside upload directories. Raw keyboard access is an explicit root-controlled
opt-in with a constrained path and documented broad access/revocation semantics.
Kernel updates authenticate RPMs against a reviewed Fedora key and reject
downgrades. Home configuration inputs are validated against the current account
and catalog before activation.

## Remaining coverage and operational improvements

Before calling a release comprehensively qualified, collect runtime evidence for
effective Nix trusted/allowed users and sandboxing, firewall and listening ports,
SSH/PAM authentication, effective SELinux module contents, Secure Boot and disk
encryption on physical hardware, and successful application security updates.
Container/VM checks do not establish those properties on a user's installation.

Prioritize these follow-ups alongside the findings:

- Record installed application inventories and update age across Nix, Brew and
  Flatpak. Keep the selected manual-update policy; make overdue security updates
  visible. The current app-status helper compares lock graphs, not advisories.
- Add reviewed static/security scan results to CI and retain narrow false-positive
  suppressions. Avoid a blanket exclusion of kernel policy files for secret scans.
- Add a private vulnerability reporting route and a security-support policy.
  Test credential revocation and workstation data restoration; OS rollback is
  not a backup of mutable user data.
- Review sandboxing of individual root/user services with installed-runtime
  evidence. Do not apply generic restrictions to the Nix daemon that break its
  required build and namespace behavior.

## Treatment sequence and maintenance

Within seven days: implement R2 and R3 with the negative tests above, establish
R1's digest-bound inventory/scan path, and validate R4 in a disposable VM. Treat
R4 as a release blocker if untrusted provisioning media executes privileged
actions in a normal installation. Within 30 days: complete upstream authenticity
and credential-boundary work, then measure application patch lag and recovery.

Reassess after these fixes, after changing trust roots/App permissions, after
major base-image or installer changes, and after any credential incident. Review
the register monthly and rerun a full assessment quarterly. Newly confirmed
applicable exploitation should receive same-day triage. Risk acceptance belongs
to the repository owner; this report does not silently accept any finding.

## Primary references

- [NIST SP 800-30 Rev. 1](https://csrc.nist.gov/pubs/sp/800/30/r1/final)
- [GitHub Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use)
- [GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments)
- [GitHub App installation tokens](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app)
- [Cloud-init NoCloud datasource](https://docs.cloud-init.io/en/26.1/reference/datasources/nocloud.html)
- [Cloud-init configuration formats](https://docs.cloud-init.io/en/latest/explanation/configuration.html)
- [Grype](https://github.com/anchore/grype)
- [Anchore vulnerability matching](https://docs.anchore.com/current/docs/vulnerability_management/how_it_works/)

Raw local evidence is under `/tmp/finite-cyber-audit/`, including redacted scanner
reports, the policy-gap fixture, the SELinux reproduction result and GitHub
metadata. No report or finding was published to GitHub as part of this audit.
