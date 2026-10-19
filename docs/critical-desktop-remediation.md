> Historical record: October 12–13 vulnerability remediation. For current operations, use
> [CI and releases](ci-and-releases.md) and [security review](security-review.md).
> See [reports](reports.md) for dated evidence and related work.

> Superseding decision: scanner advisory pairs are review work, not release
> blockers. Only exact-candidate, evidence-backed Critical desktop risks block.
> The investigations below remain tracked and can proceed independently of
> qualification; their unresolved status does not itself hold release.
> See [the current acceptance contract](desktop-release-qualification.md#evidence-based-blocking-decision).

# Critical desktop remediation sequence

The release owner's evidence-based Critical policy is implemented in PR151.
Source checks and a lower scanner count are not proof of vulnerability removal. See the
[exact-candidate ledger](critical-desktop-policy-evidence-2026-10-13.json).

Standard Generic goes first. Next and development qualify independently. No
hardware test is required; the exact candidate still needs the signed,
SELinux-enforcing VM installation/upgrade/rollback packet.

## Remaining priority investigations

| Finding | Evidence and next action | Owner |
| --- | --- | --- |
| CVE-2026-27143 / GO-2026-4868 | CISA ADP rates9.8 Critical. Go describes compiler-generated invalid indexing. Identify and rebuild/remove affected gum, glow and toolbox owning binaries; an installed compiler update does not repair them. | Finite validates consumers; package maintainers supply rebuilt signed packages. |
| GO-2026-6612 / CVE-2026-78663 | CISA ADP rates9.1 Critical; Go describes HTTP/2 flow-control resource exhaustion. Review each actual server caller; client-only behavior may justify individual nonapplicability but cannot be assumed for all container/VPN tools. | Finite exact consumer review. |
| rclone GHSA-p569-5gjg-9cmj and GHSA-xwwr-4h3p-r22c | Publisher rates9.1/9.8 Critical. Conditional server auth-proxy/signature bypasses need a signed owning fix or validated removal. The ordinary CLI and RC-started servers have different paths. | Fedora promotion; Finite compatibility/removal proof. |
| AnyIO GHSA-82r6-8w77-94w6 | Publisher rates9.3 Critical. Unicode hostname handling can bypass TLS identity checks after traffic redirection. A signed fix/backport or complete affected-consumer remediation is needed. HTTPX normalization alone does not prove all callers safe. | Fedora/Bluefin package owner; Finite caller/removal proof. |

This prioritization is not exhaustive; the ledger retains every remaining
Critical pair, including related-advisory severity and exact observed locations.
Critical applicability unknowns remain explicitly unverified. SELinux enforcing
does not itself prove application authentication or TLS checks are protected.

The first safe-removal probe is an offline, declined DNF transaction for each of
rclone, python3-anyio, gum, glow and toolbox on the latest standard digest. It
must identify collateral removals and inherited ujust/system callers before any
package change. A missing cache or solver failure is a probe error, not a safe
removal result. Boot/container functionality and retained OSTree paths remain in
scope. No removal is authorized by the probe's mere success.

## Official review evidence

Great CTO security review verified these records on2026-10-13; no severity
false-positive disposition was granted:

- [Go compiler advisory](https://pkg.go.dev/vuln/GO-2026-4868) and
  [CVE record](https://github.com/CVEProject/cvelistV5/blob/main/cves/2026/27xxx/CVE-2026-27143.json):
  recordSHA256 `80df4f78239c698bfa1cbdc4631c6799c381fe37c06e486add395e8b06d49041`.
- [Go HTTP/2 advisory](https://pkg.go.dev/vuln/GO-2026-6612) and
  [CVE record](https://github.com/CVEProject/cvelistV5/blob/main/cves/2026/78xxx/CVE-2026-78663.json):
  recordSHA256 `2efb863574d2255c66a566066670c1c0d4849f37c7652b9578b64bc90af71280`.
  These two Go CNA records supply no alternative CVSS score; the listed Critical
  ratings come from CISA ADP. A difference in impact wording warrants review,
  not an automatic severity override.
- [AnyIO publisher advisory](https://github.com/agronholm/anyio/security/advisories/GHSA-82r6-8w77-94w6):
  APIresponseSHA256 `7bdbdd6cab489005e57beb86568db59fc57df744e4174df6fda58a31b09c123a`.
- [rclone RC advisory](https://github.com/rclone/rclone/security/advisories/GHSA-p569-5gjg-9cmj):
  APIresponseSHA256 `cfaf272893863b117e8d4e88739674c50441875b744b1fb3fdb12c1665294d1f`.
- [rclone S3 advisory](https://github.com/rclone/rclone/security/advisories/GHSA-xwwr-4h3p-r22c):
  APIresponseSHA256 `041933bf1e481fcccdb7219a617b4f07b78549d1bd91184c0466ca5d2ee26508`.

## Actual removal preview

[Hosted run38411928635](https://github.com/closure-labs/finite/actions/runs/38411928635)
completed all five declined transactions on standard digest
`sha256:3b18003a2267bf22b455254f29c9324805c48cfff0f9115d00a77d041035eece`.
[Retained transaction/caller evidence](desktop-removal-evidence-2026-10-13.json)
shows rclone removes alone; AnyIO also removes python3-httpx. Gum and glow remove
alone at the RPM level but inherited desktop commands actively call them. Gum
is used for factory-reset, installation, developer-mode and update confirmations;
glow renders changelogs. Toolbox removal needs supported container-use validation.
The bounded caller search completed645 files without truncation/errors; it is
not an exhaustive runtime consumer proof. No package was removed.

Proceed with rclone removal compatibility and AnyIO/HTTPX consumer review first.
Preserve gum until a rebuilt signed owning package or compatible command replacement
is validated. These are concrete implementation dependencies, not a reason to waive
remaining Critical findings or rebuild the unchanged image.
