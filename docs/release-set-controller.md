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

The active `release-set.yml` workflow prepares a packet through
`prepare-release-set.py` and optionally opens a bot-authored release proposal
when the review App is configured. It does not sign or publish. Retained legacy
recovery workflows cannot bypass the current decision and publication controls.
Preparation uses a successful build at the same trusted main checkout revision,
requires preserved qualified ISOs for both channels, and collects fresh scans.
The initial packet reference belongs in the PR review material or immutable
external evidence storage; refreshed evidence must not enter the immutable
release proposal envelope. Root controller integration must reauthenticate
accepted scan decisions and the merged release approval before execution.

## Approved publication and recovery

`publish-release-set.yml` is active with the configured maintainer-decision
mode, App and approved baseline. Dispatch on main with the merged
proposal's full canonical hash. Preparation reauthenticates that proposal,
resolves exactly one initial packet reference from its originating bot PR body,
fetches by OCI digest, checks the successful trusted release-set producer, and
checks every approved product hash. The PR body is a discovery aid, never authority.
It rescans both images and rechecks current human findings admission.
If transient commit-to-PR association reads exhaust retries, provenance discovery
can read the complete bounded closed-PR inventory instead. The proposal's latest
commit on main must equal exactly one eligible merged PR's head or merge commit,
and that PR is read again to detect changes. Missing or ambiguous matches,
incomplete inventories, authentication failures and malformed responses stop
execution. This discovery fallback does not grant approval: the reviewed and
merged proposal bytes, ancestry and current human authority are still checked.
Large transfers finish before the final authority token is issued. The publisher
first checks live release approval, then stages the OCI products and original
Actions ZIP using the job's read-only artifact credential. This keeps archive
retries from consuming the one-hour App installation token used for team and
security-decision authentication. A fresh repository-scoped App token is issued
after staging and its private key is cleared before scans run.

The scan phase fetches the immutable OCI manifest again, rehashes every staged
member, reauthenticates the original artifact producer and ZIP size/digest, and
compares every archived member with the approved products. Staged bytes are
never trusted merely because a prior step succeeded. Missing or changed bytes
fail rather than being silently redownloaded during authority processing. The
temporary ZIP is deleted before scans and excluded from retained evidence.
Signing and publishing jobs also renew authority credentials after evidence or
product transfers and tool realization, before checking admission or exposing
signing/publishing credentials. All live human approval and signature
checks remain enforced.

Inventory reuse authenticates this publishing workflow on trusted hosted main
for its push and manual dispatch events, as well as the manual preparation
workflow. It reuses inventory bytes only; vulnerability findings, database
freshness and current security admission are evaluated again for both images.

An isolated signer job uses the main-only `release` environment without a second
manual reviewer. The release proposal supplies the human decision. It checks
current authority before exposing scoped signing keys, signs
both complete asset checksum manifests and verifies them with the public key.
A separate publisher rechecks release and security authority, verifies both
checksum bundles and exact product/evidence byte coverage, stages both releases,
then publishes. Its repository-writing token is separate from the read-only
App token used for reviewer verification. All normal and legacy recovery release
workflows share `finite-official-release` concurrency.

The signer saves an immutable OCI envelope of the exact signed manifests and
reports plus the original immutable product reference; its digest appears in
the run summary. The product bytes remain in the original approved OCI packet.
Both immutable references must remain available for durable recovery. To recover a partially
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
packet. Legacy packets contain complete product bytes; new envelopes refer to
the original immutable OCI products. Both paths verify complete product hashes
and signed reports against the Cosign public key before fresh admission. Splitting drops the redundant full ISO from
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

### Upload and publication recovery

Metadata reads request origin revalidation with `Cache-Control: no-cache`.
After creating or discovering a release, the adapter rereads its exact release
ID, because the release inventory can lag creation. It checks that the ID still
belongs to the expected tag. Missing draft visibility is reported separately
from a conflicting payload marker; inspect the publishing credentials before
retrying, rather than changing ownership markers or recreating assets.

The maintained publisher runs `stage-publication`, renews the read-only review
App token and clears its private key, then runs `commit-publication`. Staging
reserves the version, reconciles source tags and owned drafts, verifies signed
products, uploads both inventories and checkpoints `staged`; it cannot publish.
Commit reacquires the CAS lease and checks current human approval, admission,
tags and complete asset hashes before publishing, with fresh authority checks at
each channel boundary. Commit cannot create tags, drafts, upload or delete assets.
The combined `publish` command remains a compatibility entry point.

Uploads use single streaming POSTs with a 300-second limit. After each ambiguous
response, remote state is reconciled before another write (at most three POSTs).
A completed matching upload succeeds even if its response was lost. Under the
exclusive release lease, the controller may delete only an expected empty
`starter` asset in the matching unpublished draft, after rereading the individual
asset, draft and source tag. Manual concurrent asset editing is unsupported.
Nonempty, conflicting, unexpected or published assets remain untouched and require
inspection. Partial publication resumes the remaining channel without changing
matching published products. Journals remain evidence, never approval authority.

Original-product and execution ZIPs share `archive_read.py`: three immutable GET
attempts, each limited to 30 minutes, within one 90-minute transport deadline,
with 2- and 4-second backoff. Partial bytes are truncated before retry. HTTP
401/403/404, integrity errors and unsafe members are terminal. Native producer
and attempt authentication remains explicit in each caller. Long reads use the
read-only job token and restore the previous token on all exit paths; subsequent
workflow authority checks mint fresh App credentials.

Preparation keeps its full product tree locally and emits a separate
`release-signing-request-RUN-ATTEMPT` artifact containing only release documents,
scan output, derived signing evidence and a preparation identity. Compressed and
expanded evidence are bounded to 2 GiB and regular safe members. JSON evidence
uses compression level 6; the bound accommodates the existing 94/128 MB SPDX
reports and native scanner inventories while excluding ISO payloads. Consumers
verify the native artifact's repository/run/attempt/revision and ZIP digest, then
require exactly one completed successful native preparation job from trusted
main. Missing or changed producer metadata fails closed.

The protected signer receives no ISO parts. It reauthenticates current release
approval and security admission, signs the approved core hashes together with
the actual derived evidence hashes, and checks exact checksum coverage. Signed
Actions handoffs and OCI recovery envelopes contain metadata only. The publisher
verifies this small signed envelope before fetching the original approved OCI
products once, then hashes every core file and verifies both complete signatures
before staging. The original immutable product reference must equal the one in
the approved release PR; a substituted product, payload, producer or signature
stops execution. Same-run retries authenticate the actual producing attempt,
including successful preparation/signing reused from an earlier attempt.

Older authenticated full execution ZIPs and full signed OCI recovery packets
remain readable through the compatibility path. New metadata recovery envelopes
use the same protected signer proof, original approved products and fresh scans;
they preserve existing signatures. Long recovery transfers stage before fresh
App authority checks, with cached bytes reauthenticated on the scan phase.
Preparation/publication jobs allow 240 minutes and signing allows 180 minutes.

### Publisher health correlation

Before preparation transfers, the publisher uploads a small native
`release-execution-identity-RUN-ATTEMPT` artifact containing proposal hash,
payload digest, version, repository, workflow, run, attempt and workflow revision.
It is discovery metadata and never approval authority. Delivery health checks
its exact native artifact binding, archive digest and bounded JSON (64 KiB)
before correlating it with the canonical merged decision.
For publication-only retries, health may use the latest earlier identity only
after authenticating its native producing attempt and proving that both attempts
share the same successful preparation start and completion times. It still
checks the original archive digest, JSON bounds, revision and decision identity,
and reports the current attempt's status and phase. A malformed current identity
cannot fall back to an earlier one. Changed preparation or missing native proof
remains unknown.

Health reports `not_started`, `queued`, `running`, `waiting_approval`, `failed`,
`partial`, `published` or `unknown`, with the native run link and failing or
blocked phase when available. A successful build or recorded decision does not
prove publication. Public products are checked independently; failed, partial,
missing and uncorrelated publication states are unhealthy. A verified native
`release` environment wait is an informational blocker. Legacy runs without
identity metadata remain unknown and require native-run inspection. Health reads
metadata only; it does not approve, clean assets, dispatch preparation or restart
publication. Explicit recovery continues to use the original approved bytes.

### First-login readiness rollout

The OS change requires independent successful `is-active` checks for
`nix-daemon.socket` and `determinate-nixd.socket`. An existing Home Manager
configuration still exits immediately; a new configuration keeps the bounded
wait and user-journal failure diagnostic. Deliver this separately from the
controller changes and qualify the new image through both normal fresh-install
and upgrade VM jobs before merging. Do not rebuild, cancel, redispatch or approve
the existing `0.8.2-dev` execution to roll out controller changes; it remains
bound to its original revision and approved product bytes.
