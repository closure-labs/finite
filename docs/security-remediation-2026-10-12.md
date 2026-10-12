# Image scan remediation and CI tool reuse

This follow-up builds on PR #139 in a separate Jujutsu change. It does not
replace the existing signing, publication, inventory, or policy boundaries.

The [completed scan](https://github.com/closure-labs/finite/actions/runs/38290632761)
blocked the signed image
`ghcr.io/closure-labs/finite@sha256:302f05b64f6d38ce3747de84342fedd519495efa6b195f5f0dccfbe887f25d8d`.
Its 778 blocking records represent 281 distinct component/advisory pairs:
26 Critical and 255 High, including 58 RPM pairs. These are scanner matches,
not a claim that every advisory is exploitable in Finite.

[The remediation ledger](security-remediation-2026-10-12.json) retains all
281 pairs, occurrence counts, source run, image identity, and source-result
hash. Deduplication is for tracking only; it does not change scan enforcement.
No finding is marked resolved before a scan of the rebuilt image.

## Targeted RPM remediation

The build applies minimum fixed versions for installed packages in these
families, using the Fedora fix versions reported by the scan:

| Family | Minimum fixed EVR | Packages covered |
| --- | --- | --- |
| Python | `0:3.14.8-1.fc44` | python3, python3-libs, python-unversioned-command |
| sudo | `0:1.9.17-10.p2.fc44` | sudo, sudo-python-plugin |
| X11 | `0:1.8.13-3.fc44` | libX11, libX11-common, libX11-xcb |
| HPLIP | `0:3.26.6-1.fc44` | hplip, hplip-common, hplip-libs, libsane-hpaio |
| FreeRDP | `2:3.32.1-1.fc44` | freerdp-libs, libwinpr |
| Tesseract | `0:5.5.3-2.fc44` | tesseract-common, tesseract-libs |

Only already-installed packages below their floors require a transaction.
The check uses RPM version ordering, including epochs. An unavailable fix or
an unsatisfied floor fails the build. Absent optional packages are not installed.
Kernel and boot-stack packages remain outside this transaction. The full native
image scan remains authoritative for publication.

These floors come from the recorded Fedora vulnerability feed. Live Bodhi pages
were unavailable during this review. A hosted Fedora 44 metadata probe now
confirms all 16 floors are available; actual transaction and image validation
remain separate requirements. This is a targeted remediation attempt, not evidence
that the new image is clean.

## Remaining scan findings

Both approved Bluefin stable digests were resolved and authenticated again on
2026-10-12; they already match the current recipe pins. There is no newer stable
base to substitute at the time of this review.

Embedded Go modules in podman, buildah, skopeo, cosign, tailscale, rclone, and
other inherited binaries require rebuilt owning packages. Installing a newer Go
compiler does not repair those binaries. AnyIO requires its owning Python package
to be updated. The generic kernel finding requires an authenticated upstream
kernel/base update and boot qualification. The next-kernel profile has a separate
pinned kernel and must be assessed by its own image scan.

Inventory also contains OSTree object paths alongside live executable paths.
Those objects are not deleted or excluded to reduce the match count. Reachability
and ownership need separate triage if a finding persists after an owning-package
update. No broad ignore rule or policy exception is introduced.

## CI runtime constraint

Image jobs realize the same pinned tool list once and reuse its binary directory
through `GITHUB_PATH`, replacing seven development-shell invocations. Host
Determinate Nix and the verified BlueBuild binary remain on PATH. Lightweight
exports also avoid root-flake evaluation for source updates and lock validation.
The lock updater retains its exact pinned devenv dependency graph.

No Nix setup is added to documentation, signing, ISO, or VM jobs. The manual CI
benchmark compares fresh-runner and repeated execution for the old and new tool
setup. Two hosted benchmark pairs measured lower cold and warm tool-setup time:
37.63s/9.12s became 12.78s/1.08s in the first pair, and 32.49s/7.11s became
9.17s/2.11s in the second. These are setup measurements, not whole image-job
speedups. [Raw paired results](ci-tool-benchmark-2026-10-12.json) retain the
matching runner, lock and Nix versions. Compare actual image-job timing as well;
revert the tool-environment change if it adds unnecessary total time.
The targeted RPM transaction is required security work and skips network access
when all installed package floors are already met.

## Validation required before release

- Hosted image builds must prove the fixed RPMs are available and satisfy floors.
- Fresh native scans must reassess every finding against the rebuilt image digest.
- Existing signing and VM qualification gates must pass before promotion.
- Cold and warm CI measurements must justify retaining the tool reuse change.

The original image remains policy-blocked. Local fixture tests do not establish
package availability, vulnerability resolution, or boot compatibility.

## Follow-up validation

[The implementation plan](validation-remediation-plan.md) records the staged
validation sequence. [Hosted prerequisite evidence](remediation-prerequisite-evidence-2026-10-12.json)
identifies package owners and available versions. AnyIO, msgpack and rclone
remain below their advisory fix versions in the approved repositories; queried
Go-owning RPMs are already at their newest Fedora versions. Preflight reports
these as scan-readiness blockers. It does not substitute for native image scans.

## Continued vendor remediation

A new installed-only Tailscale floor uses an exact locked, signed stable vendor
RPM. Actual hosted package inspection confirmed newer embedded modules; Go and
x/net fix prerequisites still remain unmet. See the
[continued plan and residual owners](validation-remediation-plan.md) and
[signature/module evidence](security-continuation-evidence-2026-10-12.json).
This partial update does not close baseline ledger findings or establish release
eligibility. The final original four-profile matrix passed at `f506ae341663`;
current continuation validation is tracked on PR #140.
