# Decision reconciliation packet staging, October 25 UTC

The reconciler visits each profile's active accepted decision independently.
When both leaves refer to the same immutable two-profile OCI packet, it currently
downloads every member again for the second profile. This also happens when
both candidates have already been dispatched. The first successful dispatch
still ends the invocation, so an invocation visiting only one profile has no
duplicate to remove.

The packet accepted through PR 254 has OCI manifest digest
`sha256:a779c7c762144ba27e4cbe1bc5c2ea0e987495c9833cb2a0e880576c7fee80d7`.
Its [retained manifest observation](ci-decision-packet-staging-2026-10-25.json.gz)
was fetched anonymously and verified against that digest, without downloading
any evidence blobs. The observation's SHA-256 is
`ea6d61f6ea85ba9d4008d80c032eb4bb69217798d2369c166135eabfd9f8f3f2`. The manifest declares 35 layers totaling
497,913,116 bytes per full fetch. These are declared payload bytes, not measured
wire traffic or runner savings; retries and protocol overhead remain unknown.

## Prototype behavior

Stage one packet for the lifetime of a reconciliation invocation. The key binds
both immutable OCI reference and expected canonical packet hash. For the second
profile using that key, use the existing staged-packet verification path:

- Fetch and authenticate the OCI manifest again.
- Check the exact complete local inventory, regular-file paths, sizes and every
  member hash, including the approved packet manifest.
- Reevaluate that profile's native scan health and live human authority.
- Preserve the existing claim, lease, lost-response, source and publication checks.

For this shared packet, the second visit avoids 35 blob-fetch commands and one
497,913,116-byte declared payload. Both manifest reads and both full hash passes
remain. Distinct packet keys discard the previous staging directory before
fetching another, so at most one packet is retained. Interrupted fetches,
verification failures, normal returns and dispatch exits clean up staging.
Nothing persists into another invocation.

The image-selection contract also names this existing post-build controller
explicitly alongside the other decision controls. Its changes still require
source checks while selecting no OS image rebuilds. New unclassified controllers
continue to take the conservative image path. Image identity and governed human
review boundaries are unchanged.

This remains a draft prototype until hosted checks and human review complete.
Use naturally occurring reconciliation runs to measure complete-job cost,
transfer, repeated hashing, setup and cleanup. No complete-job speedup or net
recurring saving is claimed yet. No full VM round is needed to populate this
measurement. Release-product ZIP verification and the earlier failed transport
benchmark decision remain unchanged; this prototype concerns the security
decision controller's own OCI packet.
