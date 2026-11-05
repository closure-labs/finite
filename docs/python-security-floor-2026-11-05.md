# Fedora Python security floor

FINite's existing Python floor accepts `0:3.14.8-1.fc44`. The remediation script
returns before repository access when every installed floor is already met, so
rebuilding the pinned Bluefin images does not necessarily upgrade that Python.
Both profiles use the same signed Fedora remediation step in `shared/base.yml`.

The Python Software Foundation's
[CVE-2026-12345 record](https://www.cve.org/CVERecord?id=CVE-2026-12345)
identifies the `tempfile.TemporaryDirectory` cleanup race and lists Python 3.14
versions below 3.14.9 as affected. The
[upstream issue](https://github.com/python/cpython/issues/157579) and
[release notes](https://blog.python.org/2026/10/python-3152-31410-31318-31216-31118/)
document its fix. Platform limitations in the upstream advisory still apply;
this floor is not a claim that every temporary-directory race is eliminated.

Fedora's [FEDORA-2026-2a34d74310](https://bodhi.fedoraproject.org/updates/FEDORA-2026-2a34d74310)
reports the signed `python3.14-3.14.10-1.fc44` build as stable, pushed on
2026-11-04 at 01:35:24 UTC. Its security bugs include CVE-2026-12345. The Fedora
package pages list `python3`, `python3-libs` and `python-unversioned-command`
at 3.14.10-1.fc44. Python 3.14.10 also contains later security fixes; 3.14.9
was superseded by this signed stable update.

Raise those three existing floors to `0:3.14.10-1.fc44`, retain their earlier
CVE-2026-19445 association, and add CVE-2026-12345 with the current Fedora update
reference. Other package floors and the historical assessment header remain
unchanged. The transaction still updates only installed targets, uses signed
Fedora stable repositories, forbids downgrades, preserves architectures and the
protected boot stack, and fails on unavailable repositories or unsatisfied floors.
There are no scanner exclusions or changes to findings acceptance.

## Validation boundary

All three exact stable RPMs were downloaded from Fedora's official updates
server and checked read-only with native `rpmkeys`: their OpenPGP signatures,
header SHA-256 and payload SHA-256 checks passed against the existing Fedora 44
key `36F612DCF27F7D1A48A835E4DBFCF71C6D9F90A6`. Header queries confirmed epoch 0,
version-release `3.14.10-1.fc44`, x86_64 interpreter/libraries, noarch command and
the common `python3.14-3.14.10-1.fc44.src.rpm` source. This proves the RPMs are
available and signed; it does not prove their installation in a built candidate.

Offline transactions cover both profile call sites and all three packages,
including 3.14.8/3.14.9 upgrades, current/newer no-network behavior, missing or
stale post-transaction packages, multilib loss and unchanged signing constraints.
Native RPM version comparison verifies the 3.14.8 < 3.14.9 < 3.14.10 ordering;
the test mock uses numeric components rather than lexical string ordering.

Actual installed candidate RPMs and fresh scan outcomes must be established
for both profiles through hosted validation. No heavy local image build or
production image publication is part of this patch. Archived OSTree objects or
other bundled Python copies may continue to be catalogued; those findings need
their own location/provenance assessment and remain visible. This remediation
does not approve or supersede [pending review #376](https://github.com/closure-labs/finite/pull/376).
