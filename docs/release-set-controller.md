# Two-image release coordinator integration

`scripts/ci/release-set.py prepare --payload payload.json --evidence evidence.json --output release-set.json`
validates and prints the SHA-256 approval identity. There is deliberately no
standalone execution CLI: a supplied digest is not proof of maintainer approval.

The version-1 envelope has `schema`, `payload`, and `evidence`. The immutable
payload contains `version`, `sourceRevision`, and `channels`, with exactly
`finite` and `finite-dev`. Each channel contains canonical `tag`, `imageDigest`
(`sha256:…`), `isoSha256`, and `assets` (safe basename to SHA-256 hex mapping).
The version is either numeric `MAJOR.MINOR.PATCH` or its development prerelease
`MAJOR.MINOR.PATCH-dev`. Prerelease identity is derived from this reviewed version,
not a publication input. Both GitHub pages must retain that prerelease flag and
cannot become latest. See [the release lifecycle](ci-and-releases.md#publish-a-release)
for the stable-pair prerequisite and reviewed next-development PR.

Only immutable product assets belong in this mapping. Large qualified ISOs are
deterministically split into 1900 MiB parts before approval; `isoSha256` retains
the original whole-ISO identity while `assets` binds the actual upload parts. Changing any core asset,
image, qualified ISO, version, or revision changes the approval identity.

`evidence` contains one receipt per channel: `status: qualified`,
`sourceRevision`, `imageDigest`, and `isoSha256`, plus optional refreshed scan or
producer evidence. Refreshing evidence preserves the payload identity.
`prepare` checks identity consistency; it does **not** authenticate receipts.
The controller must produce these receipts using the existing authenticated
release-evidence collection/qualification checks and validate fresh scan and
human-risk authorization before executing.

The controller then calls:

```python
execute(document, GitHubClient(repository), asset_roots,
        approved_digest=authenticated_approval.payload_digest,
        owner=f'{run_id}-{run_attempt}',
        derived_assets=signed_evidence_hashes, evidence_validator=validate_signed)
```

The caller must obtain `authenticated_approval` from fresh GitHub authority
validation after the single protected release approval. Both channel asset
roots must already exist and all bytes must match. Fresh reports, signed
checksums, signatures, and derived manifests are outside the core approval
identity. The controller must validate them using existing release evidence and
signing helpers; the executor validates signed checksum coverage of every core and derived byte
before staging either release. Unsigned core-only publication is rejected.
Do not insert changing derived files into the immutable core approval mapping.

The client persists execution journals under `releases/<payload-digest>.json`
and permanent version reservations under `versions/<version>.json` on
`automation/release-journal`. Protect that branch against deletion, force push,
and arbitrary writers; allow only the scoped release controller identity.
Reservations stop competing payloads from claiming the same release version.
A compare-and-swap journal lease serializes executors of one payload for 15
minutes and renews before each bounded operation. Retries after a crash must
wait for expiry, then reconcile remote state. Journal state never substitutes
for checking remote tag targets, release ownership markers, and asset digests.
The GitHub adapter requires API-provided SHA-256 digests on uploaded assets;
older assets without a digest need a separately designed authenticated download
verification path rather than an automatic fallback.

Both releases are staged before the first is published. Existing exact tags
without releases and interrupted draft uploads resume safely. Existing foreign
release markers, unexpected assets, changed bytes, or retargeted tags fail.
There is no overwrite, delete, or retarget operation. GitHub cannot publish two
releases atomically: failure after the first publish records `partial`; retry
reconciles and finishes the second. Keep this state visible in the controller
summary and notify maintainers through the normal workflow failure mechanism.

Validation: `python3 tests/ci/release-set.py` exercises the injected client,
including partial execution, permanent version conflicts, CAS contention,
changed remote assets, local symlinks, mismatched qualification, and idempotent
retry. No live release is created by these tests.

The additive `release-set.yml` workflow prepares a packet through
`prepare-release-set.py` and optionally opens a bot-authored release proposal
when the review App is configured. It does not sign or publish. It retains the
legacy release workflows and their existing approval gates during rollout.
Preparation uses a successful build at the same trusted main checkout revision,
requires preserved qualified ISOs for both channels, and collects fresh scans.
The initial packet reference belongs in the PR review material or immutable
external evidence storage; refreshed evidence must not enter the immutable
release proposal envelope. Root controller integration must reauthenticate
accepted scan decisions and the merged release approval before execution.

## Approved publication and recovery

`publish-release-set.yml` is additive and inactive until the maintainer-decision
mode, App and baseline are correctly configured. Dispatch on main with the merged
proposal's full canonical hash. Preparation reauthenticates that proposal,
resolves exactly one initial packet reference from its originating bot PR body,
fetches by OCI digest, checks the successful trusted release-set producer, and
checks every approved product hash. The PR body is a discovery aid, never authority.
It rescans both images and rechecks current human findings admission.

An isolated signer job retains the existing `release` environment reviewer during
migration. It checks current authority before exposing scoped signing keys, signs
both complete asset checksum manifests and verifies them with the public key.
A separate publisher rechecks release and security authority, verifies both
checksum bundles and exact product/evidence byte coverage, stages both releases,
then publishes. Its repository-writing token is separate from the read-only
App token used for reviewer verification. All normal and legacy recovery release
workflows share `finite-official-release` concurrency.

The signer saves an immutable OCI packet of the exact signed products and
reports; its digest reference appears in the run summary. To recover a partially
published release in a new dispatch, provide that reference as `packet_ref`.
Recovery checks the trusted signing job, signatures and equality with the approved
core, rescans both images, and retains the original signed bytes. It does not
regenerate signatures or replace remote assets. A same-run failed-job retry
resolves the authenticated prior artifact-producing attempt and verifies its ZIP
digest and bounded regular members before extraction. Expired signed artifacts
require the immutable signed OCI packet. Missing or conflicting remote evidence
stops recovery rather than overwriting or retargeting anything.

Merging one new canonical release decision on main starts publication automatically;
manual dispatch is reserved for explicit execution or recovery. The push handler
uses the authenticated before/after comparison, requires exactly one newly added
release ledger record, verifies its canonical filename, and then performs the
same live human authority checks. Multiple release decisions in one push require
an explicit dispatch rather than an arbitrary selection.

An initial packet must also bind the actual uploaded
`release-set-packet-RUN-ATTEMPT` artifact. Proposal creation and initial execution
stream the original Actions ZIP, authenticate its exact size and SHA-256, reject
unsafe or duplicate members, and compare every file hash with the OCI packet.
The immutable archive GET allows three attempts of at most 30 minutes each for
transport timeouts, connection interruptions and transient HTTP failures, with
2- and 4-second backoff. Every retry discards partial bytes and obtains a fresh
download response. Authorization errors, missing artifacts and all size, digest
or member validation failures stop immediately. Repository and registry writes
do not use this retry path.
A successful workflow ID plus self-reported packet metadata is insufficient.
If the original artifact expired, use the previously persisted signed recovery
packet, whose complete product bytes and reports are checked against the Cosign
public key before fresh admission. Splitting drops the redundant full ISO from
persisted products after verifying its original qualified hash; signed staging
uses hardlinks for verified core files to avoid duplicate large allocations.

The publishing job uses the existing `MERGE_QUEUE_PAT` through the standalone
`release-set-publishing` SecretSpec scope for `RELEASE_PUBLISH_TOKEN`. Its existing
Contents/Workflows permissions support tags pointing at approved historical
commits after workflow files change. `GH_TOKEN` remains the separate read-only
App token for live human authority checks. The scoped publisher inherits neither
signing keys, the App private key nor cache/updater credentials. Neither the
scanner nor signer receives this PAT, and publishing tools are realized before
it enters the isolated child process. The review App gains no Workflows permission.
