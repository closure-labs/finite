# Desktop release qualification

Finite uses Bluefin/bootc with Nix/Home Manager and SELinux. Qualification is
per channel and per immutable image; standard generic can qualify independently
of development and Next. Source checks, vulnerability clearance, automated boot
qualification and desktop release approval are separate results.

## Security acceptance

A clean scanner count is not required. The upstream-maintained risk policy keeps
all findings visible while blocking reviewed Critical vulnerabilities with evidence of an affected shipped component,
a reachable supported desktop attack path, and relevant SELinux conditions.
A confirmed Critical risk must be fixed, removed with the affected feature, or
shown inapplicable/backported using exact package/file/caller evidence. Scanner
matches and unresolved applicability alone are advisory review work, not release
blockers. Acceptance of these unknowns is not a claim they are harmless or fixed. Lower severities,
including known-exploited findings, remain tracked risks under the release owner's
explicit Critical-only threshold; this is risk acceptance, not remediation. A signed publisher update is a remediation input,
not proof that every embedded dependency is fixed. Retained OSTree copies and
container/development use remain in scope.

SELinux enforcing is necessary, but does not prove that a process is confined.
Candidate evidence must retain actual domains, permissive types and listeners.
Unconfined domains are recorded honestly, rather than treated as either an
automatic vulnerability or a blanket mitigation. A mitigation claim needs proof
that the relevant operation is denied in the affected domain with the supported
configuration. No permissive workaround or automatic allow-rule generation is
part of qualification.

## Qualification sequence

1. Complete inexpensive source and package compatibility checks, and verify
   approved signed owning-package availability.
2. Build one genuinely changed representative image. Bind a fresh native scan,
   policy result and package evidence to its immutable digest.
3. Run existing hosted Secure Boot/encrypted-install, upgrade and rollback tests.
   Retain candidate-phase SELinux/process/network receipts with hashes, without
   applying new candidate assertions to historical predecessor/rollback images.
4. Treat the successful VM qualification as sufficient desktop qualification,
   as explicitly selected by the release owner. No separate physical-hardware
   or manual graphical-desktop test is required for eligibility.
5. Review the exact-image security, signing and VM packet through the existing
   protected release environment before publication.

VM evidence must identify what was actually tested. Untested physical devices
or graphical interactions remain informational coverage limits, not extra
release blockers. Passing a VM does not waive an applicable Critical vulnerability,
failed SELinux checks, missing signatures or a failed upgrade/rollback test.

## Current work and external prerequisites

See [the execution sequence](release-implementation-sequence.md) for exact runs,
image bindings and current blockers. Reuse valid evidence and avoid another scan
of an unchanged known-blocked image. Hosted resources perform all candidate,
package execution, scan and VM work; the workstation runs bounded fixture tests.

## Automated receipt

The candidate VM records userspace and kernel SELinux enforcement, permissive
domain inventory, process contexts and TCP/UDP listeners. The SSH fixture must
run in enforcing sshd_t; other domains remain accurately recorded. These
observations do not claim every application is confined or every listener safe.

The receipt includes the exact raw candidate manifest and booted image digest,
profile, source revision and build identity. Fresh installation and, when a
predecessor exists, the upgraded candidate each need observations. Their combined
receipt is hashed into acceptance and rechecked before promotion and durable
release. The historical predecessor and rollback retain their existing tests;
new candidate assertions are not retroactively imposed on them.

[Retained package evidence](vm-tool-prerequisites-2026-10-13.json) confirms the
standard candidate carries Python, procps, iproute and SELinux policy utilities.
The actual future VM must still execute its tools successfully. No new image or
VM pass is claimed by fixture tests or historical package presence.

## Critical-only release decision (2026-10-13)

The release owner requested: “only block release if its a critical cev for desktop
se linux users”. The implemented `desktop-critical-only` mode interprets this as
Critical severity on any native scanner primary or related advisory alias, with
all four desktop profiles and supported container tools in scope. Renaming a CVE
as a GHSA or GO advisory must not bypass the threshold. Critical applicability
unknowns remain nonblocking review work; they are not assertions of proven
exploitation or of safety. A severity rating and package/advisory pair alone
cannot establish a blocking desktop risk.

SELinux enforcement alone cannot dismiss a finding: desktop processes can be
unconfined and user data remains valuable. Existing digest/package/path-bound
nonapplicability and backport evidence still applies only within its exact scope.
Routine risk waivers cannot clear confirmed Critical desktop risks.

Lower-severity and unrated source concerns remain recorded, including Next's
unrated kernel hold; they no longer categorically block vulnerability clearance.
Likewise, an optional package upgrade's availability or incomplete compatibility
work does not block release unless that upgrade is needed to resolve a remaining
Critical finding. Adoption of any new package still requires approved signed
sources and compatibility validation.

Invalid, stale or missing security evidence is a verification error, not a CVE
disposition. Authenticity, build correctness, SELinux-enforcing VM qualification,
encrypted Secure Boot installation, upgrade and rollback remain required. A policy
change is not a package fix and cannot be reported as one.

## Evidence-based blocking decision

The release owner clarified that advisory pairs are insufficient to block release.
`blockingBasis: reviewed-desktop-exploitability` implements that decision explicitly.
The Critical-only threshold is necessary but not sufficient for a vulnerability
blocker. Each confirmed record must identify the exact image, profile, versioned
component and files; Critical advisory/source evidence; affected-code evidence;
a supported attacker path and preconditions; desktop impact; and the SELinux
assessment/evidence, reviewer and date. No registry-wide severity rule substitutes
for those facts. A source/caller/configuration proof can establish applicability;
a reproduced exploit is not mandatory.

Confirmed records block their exact candidate even if a scanner misses the CVE.
They are not cleared merely by expiry. Existing unconfirmed source concerns and
scanner matches remain visible without blocking. Malformed records and invalid
security evidence fail verification. A policy pass under this decision means no
confirmed blocking records for the candidate, not zero vulnerabilities or proven
safety. Existing signing, enforcing-SELinux VM and boot qualification still apply.
