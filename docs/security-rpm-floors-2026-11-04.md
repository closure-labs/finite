# Pillow and libsoup Fedora security floors

The [published-image audit](https://github.com/closure-labs/finite/actions/runs/41868131416)
at source `e4b6eb73767ba2fb165a8838d990a25f0b5edfdc` reports
`python3-pillow-12.3.0-4.fc44` and `libsoup3-3.6.6-10.fc44` in both profiles.
Its finding snapshot is proposed in [#372](https://github.com/closure-labs/finite/pull/372);
this remediation does not approve or accept that snapshot.

| Installed package | Minimum Fedora EVR | Signed stable update |
| --- | --- | --- |
| python3-pillow | `0:12.3.0-7.fc44` | [FEDORA-2026-719fffc96a](https://bodhi.fedoraproject.org/updates/FEDORA-2026-719fffc96a) |
| libsoup3 | `0:3.6.6-11.fc44` | [FEDORA-2026-f06a7887af](https://bodhi.fedoraproject.org/updates/FEDORA-2026-f06a7887af) |

Both Bodhi updates were signed and stable at 2026-11-03 01:37:18 UTC when
checked on November 4. Current Bluefin stable manifests still match the recipe
pins, version `44.20261103`; their images finished at 01:27 and 01:31 UTC,
before that stable push. Refreshing those unchanged pins would not fix this gap.
The policy's source image/run now identify the current audit; all earlier floors
remain unchanged and their history remains in Git.

Use the existing `security-remediate.py` build step. It upgrades only installed
reviewed targets through refreshed Fedora `fedora` and `updates` repositories,
requires package signature checks, forbids downgrades and excludes the protected
kernel/bootc/rpm-ostree/ostree stack. It verifies every resulting floor, installed
architecture and unchanged boot-stack inventory. An unavailable fixed package or
failed transaction stops the build; this change enables no testing/third-party
repository and adds no package-manager retry or alternate download path.

## Candidate validation

Focused fixtures cover both old RPMs, exact floors, multilib preservation,
unresolved/missing packages and the existing signed-repository transaction.
Normal unpublished branch diagnostics must build both profiles at the exact PR
head, authenticate upstream bases, verify local image identity, and retain native
SBOM/scan evidence. Check the SBOM's actual RPM release values against the floors
and bind results to the native run/attempt, source and image config/manifest hashes.
Scan health is separate from remaining findings; unpublished diagnostics never
grant signing, production publication or findings acceptance. Full queue/VM and
normal release gates remain unchanged. Hosted candidate outcomes are pending when
this draft is first published; do not treat its fixtures as image-build proof.

## Separate remaining questions

- Fedora Pillow backports keep Python metadata version `12.3.0`. RPM advisory
  findings and generic PyPI version matches can therefore disagree after the fix.
  Any remaining PyPI finding needs individual patch/file ownership evidence;
  this change adds no suppression or disposition.
- Upstream Podman `v5.8.9` contains all three `v5.8` fix commits from
  [GHSA-2cvf-wqm6-wr9g](https://github.com/podman-container-tools/podman/security/advisories/GHSA-2cvf-wqm6-wr9g).
  Fedora's current Podman spec selects that tag. Installed binary/source binding
  remains distinct from a dirty Go pseudo-version in scanner metadata.
- `podman-tui` is a separate consumer: its upstream
  [v1.11.3 go.mod](https://github.com/containers/podman-tui/blob/v1.11.3/go.mod)
  still requires Podman `v5.8.4`, matching the additional finite-dev finding.
  Updating the Podman CLI RPM does not update that compiled dependency. Reachability
  and a separately built fixed consumer remain unproven; no exception is granted.
- Fedora's [certifi spec](https://src.fedoraproject.org/rpms/python-certifi/raw/f44/f/python-certifi.spec)
  removes bundled PEMs and tests use of the system trust bundle at
  `/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`. The image's actual trust
  contents still need checking for the emSign advisory. No certifi finding is
  dismissed on the basis of packaging metadata alone.
