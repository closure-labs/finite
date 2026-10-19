# Security audit implementation

> Historical record: October 12 security implementation. For current operations, use
> [CI and releases](ci-and-releases.md) and [security review](security-review.md).
> See [reports](reports.md) for dated evidence and related work.

This implements the treatments in the
[12 October assessment](security-audit-2026-10-12.md). Finite remains a
Bluefin/bootc desktop with Nix and Home Manager, developed in Jujutsu.
Application updates remain manual.

## Implemented controls

| Finding | Treatment |
| --- | --- |
| R1: publication without vulnerability gate | Independently inventory and scan the immutable candidate; enforce fresh database, Fedora RPM advisory coverage, KEV and fixable High/Critical policy before signing; reevaluate evidence before promotion; daily public-channel rescans and enforcing release scans |
| R2: incomplete repository audit | Compare complete typed environment protections and effective main rules; fail on inaccessible APIs; audit hidden bypass actors separately using admin CLI |
| R3: stale SELinux module | Reinstall shipped policy transactionally on each startup, verify module presence, and fail before Nix initialization on errors |
| R4: ambient NoCloud provisioning | Install cloud-init disable sentinel and datasource restriction; remove default target enablement; assert inactive provisioning and test malicious cidata in candidate VMs |
| R5: unauthenticated base updates | Verify both approved Bluefin repositories by immutable digest against a reviewed publisher key and fingerprint, before pin mutation and candidate builds |
| R6: build-time signing key exposure | Separate builders/scanners from fresh signing jobs; restrict image signer to main and release signer to reviewed release environment; migrate existing key without rotation |

The sequence is unsigned build, independent security scan, isolated signing,
encrypted Secure Boot qualification, then exact-digest promotion. Scanner errors,
stale evidence, signature failures and failed qualification must not move public
tags. See [CI controls and exception policy](ci-and-releases.md#image-vulnerability-gate).

## Provisioning and SELinux

Ordinary images disable cloud-init through `/etc/cloud/cloud-init.disabled` and
`datasource_list: [None]`. `finite-cloud-init` remains available to generate
legacy configuration but warns that media is inert by default. Use the generated
profile with `finite-home-init --profile profile.yaml` for normal setup.

An administrator deliberately enabling cloud-init must remove the sentinel,
configure trusted datasources and enable its units. That opts into root-level
provisioning: arbitrary attached seed media must then be treated as privileged
input. Keep this restricted to controlled provisioning environments.

SELinux reconciliation installs the shipped policy every time, including rollback
to another image that contains the new reconciliation helper. Historical images
with the old install-once helper do not acquire this guarantee retroactively. It does not trust a separate version marker. Candidate
VM tests attach harmless NoCloud write_files/runcmd probes, confirm the media is
present and require no execution markers, inactive services and SELinux enforcing.
Historical predecessor images cannot satisfy newly introduced assertions, so
those assertions run on fresh candidates and after updating to the candidate.

## Credential placement and repository audit

The existing signing key was verified against `cosign.pub` and copied into
`image-signing` and `release` environment secrets on 12 October 2026. Migration
used a one-time encrypted artifact; no plaintext key was saved or displayed. The
artifact, temporary remote branch and local recipient private key were removed.
`image-signing` permits only `main` with admin bypass disabled; `release` also
requires the existing designated reviewer.

The repository-wide signing secret remains temporarily for older running
workflows. Delete it after the new workflow is merged and older workflows are
retired; until then the environment migration does not fully remove exposure.
Do not rotate the public key merely to move secret storage: installed machines
already trust the existing key.

The shared audit App retains Administration: read. GitHub hides ruleset bypass
actors unless the caller can write the ruleset. The hosted audit therefore
explicitly reports partial coverage for that field; it must never infer an empty
bypass list. The default admin CLI audit checks the complete policy, including
bypass actors. Run it after repository-policy changes and periodically:

```bash
nix run --accept-flake-config .#repository-security-audit
```

The complete admin audit passed against 18 live endpoints and all three
environments. The [hosted read-only App audit](https://github.com/closure-labs/finite/actions/runs/38282141341)
also passed its covered controls, explicitly reporting partial coverage for
ruleset bypass actors. Organization membership, access to organization secrets and secret
values remain outside the audit. A reusable App's private key retains access to
its installations even when each minted token is scoped to a single repository.
See [GitHub ruleset API visibility](https://docs.github.com/en/rest/repos/rules#get-a-repository-ruleset).

## Validation and remaining boundaries

Independent code and security reviews found no blocking source defects. Focused
regression suites passed for upstream authentication, scan policy/promotion,
unsigned builds, image inspection, provisioning, SELinux reconciliation and
release evidence. Both pinned Bluefin foundations passed live publisher-signature
verification. Actual pinned Grype schema and Fedora advisory database queries
were checked; these checks are not a scan of the current complete image.

For OCI image indexes, evidence retains the exact signed parent manifest and
the unique Linux amd64 child manifest. Policy verification hashes both raw
artifacts, verifies their descriptor relationship and binds both native scanners
to that child. The trusted scanner job uses rootless umoci to unpack the
authenticated OCI image, then inventories that directory with the image cataloger
set and a base path that prevents following links outside the rootfs. Native
Syft/Grype directory metadata is preserved. Extraction provenance records the
parent and child digests, tool version, exact source/base paths and native SBOM
hash; promotion revalidates those relationships. This relies on the trusted
scanner job, not a standalone cryptographic proof of extraction. Rootless
ownership/device emulation is appropriate for package content inventory, not
runtime permission validation. Other amd64 variants or missing manifests fail closed; signatures
and publication continue to use the original parent digest.

The [hosted native inventory](https://github.com/closure-labs/finite/actions/runs/38288928004)
completed without an OOM kill. Its post-inventory check exposed multiline umoci
version output; the parser now accepts the actual format and retains the raw
output. The [authenticated artifact continuation](https://github.com/closure-labs/finite/actions/runs/38290632761)
finished Grype and policy evaluation on the exact retained inventory. This is
validation in two hosted phases, not a claim of a successful single-run scan.

The scanned image was
`ghcr.io/closure-labs/finite@sha256:302f05b64f6d38ce3747de84342fedd519495efa6b195f5f0dccfbe887f25d8d`.
Coverage included 1,865 RPMs and 4,945 packages, with Fedora 44 established by
`fedora-release-common` version `44-18`, fresh Fedora/KEV data and four matching
database coverage-probe records. Policy **blocked** publication: 778 blocking
records reduce to 281 unique component/advisory pairs (26 Critical, 255 High),
covering 117 advisory identifiers; 58 pairs concern RPM packages. No KEV matches
were reported and no exceptions were applied. These are scanner matches requiring
triage, not 281 independently confirmed exploitable vulnerabilities.

Remediation must first map matches to their installed packages or containing
binaries, prioritize Fedora RPM updates and vulnerable bundled dependencies,
then scan the replacement immutable candidate. Existing channels are not made
safe by adding a gate. Enabling the gate intentionally prevents publication of
candidates with the same findings; no broad suppressions or thresholds were
changed to make this baseline pass. Fresh candidate signing, VM qualification
and promotion still need hosted evidence after remediation.

The local full Nix check was interrupted after workstation memory pressure.
The [hosted full Nix and runtime suite](https://github.com/closure-labs/finite/actions/runs/38282653824)
passed after fixing an undeclared test dependency and fixture interpreter path.
No full-image scan or VM qualification was run locally. Remaining image checks
run on GitHub-hosted runners. Image parsing uses a separate service capped at
the smaller of 10 GiB and measured available RAM minus 4 GiB, with no swap,
a Go soft limit at 80% of that cap and one catalog worker. Hosts with less than
5 GiB available fail before starting the scanner. The parent
retains resource diagnostics and requires an explicit passing result for the
requested digest; missing or killed scans fail closed. This resource isolation
is not a complete sandbox for hostile code. Do not claim runtime upgrade/rollback success
from mocked lifecycle tests; hosted VM evidence is still required.

BlueBuild module references and RPM repositories still trust upstream publication
and package signing; publisher verification does not make every build input
content-addressed. Manual Home Manager updates still require operator action.
The personal repository retains zero mandatory independent approvals, and its
maintenance credential remains broader than the isolated audit token. These
constraints are documented residual risks, not controls claimed as complete.
Registry build credentials still have repository-wide package write access, not
a tag-scoped capability. A compromised builder can disrupt or redirect public
tags outside the promotion workflow. Image signatures reject unsigned
replacements but cannot prevent redirecting a tag to an older legitimately signed
image or enforce current qualification. Digest and evidence checks protect the
normal publication path; eliminating this residual requires separate registry
write boundaries or an external promotion service.
