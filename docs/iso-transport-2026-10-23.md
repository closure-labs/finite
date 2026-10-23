# ISO transfer audit, October 23, 2026

Fresh qualification already constructs and boots its candidate ISO on one
runner. It does not upload a large ISO just to download it for the next phase.
The optional upgrade optimization fetches an older run's pristine predecessor
ISO, while release preparation preserves the exact bytes selected for later
approval and publication. These transfers have different purposes and costs.

## What the initial runs show

The first main run after #235,
[39980522095](https://github.com/closure-labs/finite/actions/runs/39980522095),
failed before constructing the standard image: payload identity evaluation
exceeded 300 seconds. Its developer candidate was built, scanned and signed,
then passed fresh-install acceptance with Secure Boot, encrypted root and Home
Manager configuration checks. Fresh Home Manager activation took 299 seconds.

The [developer upgrade job](https://github.com/closure-labs/finite/actions/runs/39980522095/job/120522513504)
never reached VM acceptance. Downloading predecessor artifact `12509215489`
(7,127,240,191 bytes) hit the 1,800-second transfer deadline. The authenticated
stage report measured 1,805.396 seconds and exit status 2, so the existing
status-3 installer reconstruction fallback never ran. The runner received
6,179,508,658 network bytes during that stage. This is a runner-wide counter;
it does not prove exactly how many archive bytes arrived or their per-flow rate.
Successful fresh acceptance does not qualify the whole candidate: aggregate
qualification and promotion were skipped after the upgrade failure.

The initial [#237 merge-queue run](https://github.com/closure-labs/finite/actions/runs/39990091392)
passed the new payload path on both profiles. Preparation took 11 seconds for
`finite` and 10 seconds for `finite-dev`; staging took 10 and 5 seconds. The
earlier main developer job took 24 and 4 seconds respectively, while standard
preparation timed out at 300 seconds. These are one observation per
event/profile, with different publication preflights and cache states. They
confirm execution of the new path, not matched savings or complete-job medians.
VM qualification was still running when these timings were collected.

## Immediate reliability correction

Give the optional predecessor archive transfer one 600-second attempt. Previous
successful complete restores measured 130.710 and 387.376 seconds; the new
limit leaves headroom over those observations without allowing the known
30-minute transfer failure. This is an availability budget, not an optimum
derived from a timing distribution. Metadata lookup, archive verification,
installer generation and VM execution are outside this transfer budget.

Only a timeout of that exact archive GET, with the configured timeout, becomes
status 3. The existing fallback constructs an installer for the same signed
predecessor digest and then runs upgrade/rollback acceptance. It never rebuilds
or substitutes the candidate OS image. Stop searching after this timeout;
trying older copies must not multiply the budget. HTTP authorization failures,
HTTP 416, corrupt archives, hashes, signatures and unrelated timeouts remain
terminal. No new outer download retry is added.

The shared release downloader retains its existing strict 1,800-second default.
Only opportunistic predecessor reuse opts into the shorter limit and fallback.
Timeout diagnostics now report the actual temporary archive byte count before
cleanup. No archive member is extracted until the download and archive digest
checks complete. Qualification still runs after successful reconstruction;
cache unavailability is never an acceptance result.

Regression coverage includes a real child-process timeout, discarded partial
bytes, one transfer attempt, unchanged exact predecessor identity, successful
reuse, terminal authorization/integrity/signature failures, unrelated timeout
rejection, and preservation of the release downloader's existing default.

## Which ISO transfers can be streamlined

| Path | Current behavior | Assessment |
| --- | --- | --- |
| Fresh qualification | Construct and test locally; retain the pristine ISO afterward | Keep the local execution and exact-byte preservation for release use |
| Upgrade qualification | Fetch the previous run's ISO as an optimization | Optional; bound failure and reconstruct locally when unavailable |
| Release collection | Fetch both exact qualified ISOs; upload an Actions product packet and durable OCI packet | Durable recovery and native producer binding currently depend on these copies |
| Publisher preparation | Fetch OCI products, then fetch the original Actions ZIP to authenticate the same files | Candidate for removing a redundant bulk download using native producer evidence |
| Protected signing | Transfer hashes, scan evidence and signing metadata only | Already excludes ISO product bytes; keep this boundary |
| Publication | Hydrate the exact original OCI products and verify signed hashes before uploading release assets | Fetch product bytes where needed for delivery; preserve immutable assets |

The release proposer currently authenticates the native Actions ZIP against its
local files before pushing the OCI packet. A later publisher preparation repeats
that ZIP download after fetching the same product bytes through OCI. The current
two-profile ISO archives total about 12.3 GB before other packet members; a
redundant full-packet transfer is material. The precise packet size and complete
phase cost need measurement for the selected producer.

A compatible optimization would retain a small, native producer-bound origin
receipt after the proposer has verified the original ZIP and persisted the OCI
packet. Bind repository, workflow, source, run, attempt, the actual original
artifact ID/digest, the immutable OCI reference and complete packet identity.
Publisher preparation could authenticate that receipt and every OCI product
hash instead of downloading the full original ZIP again. This receipt would
prove transport provenance only; native human approval, fresh security admission,
protected signing and version reservations would still be required.

Keep legacy packets on their existing ZIP verification path. A present but
invalid receipt must fail closed. Preserve the existing metadata-only signing
handoff, and verify forged producer identities, changed manifests, moved heads,
revoked approval, partial publication and lost upload responses before adopting
the alternative. The frozen 0.8.2-dev execution must remain on its original
products and protocol. This proposal is not implemented or enabled here.

Measure legacy and receipt paths against the same immutable two-profile packet,
including all native/OCI reads, hashing, setup, retained storage, signer handoff
and cleanup. Include failed and cancelled work. Require unchanged acceptance
and producer checks plus a repeatable complete-job saving before adoption;
reader cache hits or counting fewer steps is insufficient. Replacing the
remaining full native upload/verification with an uploader attestation is a
further proposal, not a consequence of adding this receipt.

## Status and rollback

This follow-up depends on #237. It does not amend that approved head, dispatch a
recovery, resume the failed candidate, mutate published assets or cancel an
active publication. The exact candidate, predecessor and native evidence hashes
are in the [companion record](iso-transport-2026-10-23.json).

Rollback the predecessor timeout handler to restore the former terminal behavior.
The shared release API remains compatible. Changing `release-evidence.py`
conservatively invalidates retained ISO context on first rollout, so an initial
local reconstruction is expected; later eligible restores exercise the bounded
path. Keep automatic Cachix writes and Grype DB transport disabled. The retained
OCI image-export verification alternative remains unadopted, and the seven-day
observation still ends October 30.
