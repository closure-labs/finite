# Bounded scanner cost observations, October 24, 2026 UTC

The successful [#246 main rollout](https://github.com/closure-labs/finite/actions/runs/40052937117)
retained scanner evidence archives of **33224147 bytes** for `finite` and
**43540608 bytes** for `finite-dev`. Both exceed the cost collector's 8 MiB
archive limit. Native security jobs cost 685 and 808 runner seconds,
respectively; their internal phase costs remain unknown in that observation.
The collector correctly declined the full downloads. These job durations do
not establish how much transfer, extraction, cataloging or scanning is avoidable.

Retain `phase-timings.json` separately as a native
`security-costs-PROFILE-RUN-ATTEMPT` artifact for 14 days. The same producer
continues to retain full scanner evidence for 90 days. The small projection
contains existing timings and inventory reuse observations, including partial
scanner failures. An unstarted scanner produces no invented receipt.

The read-only collector authenticates the Actions ZIP digest and binds it to
the native run, source, producing attempt and unique profile/security job.
The compact archive permits one timing member and at most 64 KiB of expanded
content. Phase durations must be finite and bounded; success is an explicit
boolean. Missing phases in older full archives remain unmeasured.

When both projections are available, they must agree. Repeated commands remain
separate samples, while duplicate full/compact artifacts and reused jobs across
retry attempts are charged once. Stage durations are nested within native job
occupancy and are never added to it. False `inventoryReused` does not establish
reuse eligibility or a cache miss. Candidate identity, tool cohort and other
unavailable fields remain unknown.

This artifact supplies cost observations only. Signing, security admission,
approval, freshness and publication continue to consume the full evidence and
retain their independent checks. The additional upload's setup, transfer and
cleanup cost remains part of the native security job. Net recurring savings
require natural rollout evidence; this change does not claim them.

Use naturally occurring runs with the existing `workflow-costs.py --receipts`
collector to rank scanner stages alongside ISO, initializer and source aggregate
work. Do not dispatch additional full VM rounds just to populate the report.
Keep this follow-up draft while Foundation v0.3.3 qualification and its first
main rollout are pending, avoiding another main advance during publication.

The original seven-day assessment endpoint remains **October 30, 05:01:17 UTC**.
The window is incomplete. Later source and Foundation cohorts remain separate.
See the [evaluation result](ci-home-proof-evaluation.md) and
[earlier optimization evidence](ci-next-optimization-2026-10-24.md).
