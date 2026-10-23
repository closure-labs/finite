# Native release product origin prototype

This draft preserves the production ZIP verification path. The optional
`origin_pilot` argument is a prototype consumer API, with no production workflow
or dispatch input enabling it. Proposal payloads, qualification receipts and
existing dispatch inputs retain their formats. No frozen execution, decision or
published asset is amended.

The proposer first authenticates the original Actions ZIP against its local
files and persists the complete packet in OCI. Only then does its native
`prepare` job write `release-set-origin.json`. The workflow uploads that small
versioned document as `release-set-origin-RUN-ATTEMPT`, with the product packet's
90-day retention. It binds repository, workflow, source revision, run, attempt,
producing job, original artifact ID/name/digest/size, immutable OCI reference,
canonical packet identity and every member's size and SHA-256.

A prototype consumer authenticates the receipt's native ZIP, the successful
same-repository main producer and its exact successful job/upload steps. It
requires complete agreement with the immutable OCI manifest and rehashes every
product. An absent receipt alone falls back to the original strict ZIP check.
Expired, ambiguous, forged or malformed receipts fail closed. Staged OCI products
and the small verified receipt ZIP survive credential renewal; both are checked
again with fresh native metadata. Approval, fresh security admission, protected
signing, reservations, stale-source checks and publication remain independent.

The diagnostic workflow has separate `produce` and `consume` invocations. Produce
accepts an existing authenticated release packet, verifies it through the legacy
path and creates a new native ZIP and OCI packet containing the identical
two-profile product inventory. Its outer producer identity is diagnostic and
cannot pass the production release producer check. It never creates approval
proposals or changes source products. Consume requires that new producer run to
have completed successfully before measuring either path.

The consumer matrix contains five warm matched pairs and one cold pair. Each
leg gets a separate hosted runner. Both warm legs include the same legacy seed
transfer and cleanup in complete-job cost. Cold means a fresh runner, with
provider-side cache state explicitly unknown. Each consumer verifies the full
inventory and retains failures and local cleanup results. Native complete-job
timestamps include setup, all transfers and hashes, retention upload and post-job
handling. Producer source verification, native upload, OCI upload, origin upload
and cleanup are measured separately and must remain in the cost assessment.

After the consumer workflow completes, run
`python3 scripts/ci/report-release-transport.py --run RUN_ID`. The report reads
bounded, digest-verified native sample archives, binds their jobs and producer,
and compares complete-job occupancy. It rejects duplicate or mismatched pairs.
Five warm pairs and one cold pair must pass correctness; warm medians must
improve by at least 10% and 30 seconds; cold cost may regress by at most 10%.
A performance pass alone never enables production.

Diagnostic Actions artifacts retain seven days of logical bytes. The OCI packet
has no automatic expiry. Its retained storage and eventual exact-reference
cleanup remain explicit missing lifecycle evidence; do not claim full storage
savings or adopt the path until those costs have been observed. Report logical
byte-days separately from deduplicated registry billing. Local cleanup does not
prove registry cleanup. Preserve the original packet and all existing decisions.

No hosted diagnostic samples have been collected for this draft. GitHub must
know the new workflow on its default branch before it can be manually dispatched
at a reviewed branch; source tests and PR aggregate checks do not establish the
benchmark gates. Keep the draft and the existing production path until the
matched measurements and lifecycle observation are complete. The seven-day CI
cost assessment still ends October 30 at `05:01:17Z`; later cohorts remain
separate. Cachix writing and Grype database transport remain disabled.
