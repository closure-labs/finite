# Source repetition and rollout evidence, October 25 UTC

Both profiles completed fresh-install and upgrade/rollback qualification and
promoted the original retained candidates after security decision 259 merged.
The [finite recovery](https://github.com/closure-labs/finite/actions/runs/40168352161)
used 3,960 runner seconds and the
[finite-dev recovery](https://github.com/closure-labs/finite/actions/runs/40171167682)
used 4,421, totaling 8,381. Native selection identified original producer
`40162236269`; candidate restore succeeded and fresh image construction was
skipped. Approval, security freshness, original provenance, signing, qualification
and promotion remained independent gates. These are different candidates from
older recoveries; the totals do not establish a causal speedup.

PR 260 then entered the protected queue automatically after both promotions.
Its [queue](https://github.com/closure-labs/finite/actions/runs/40174527617)
passed and it merged as `d3c2c2c998900000ee88fe0173e72deeff3d31e3`.
Its [main run](https://github.com/closure-labs/finite/actions/runs/40175020315)
passed and selected no images. Both authenticated source receipts name
`/nix/store/mkh5bp5p3jjffzp594gir5qm1di69mws-finite-ci-checks.drv`.

## Repeated source work is the next measured opportunity

The frozen six-workflow sample contains 73 unique native jobs and 13,358 known
runner seconds. Grouped cost conserves that complete known occupancy. The sample
is scoped to the original producer, two security-259 recoveries and their queue,
and the queue/main rollout of 260. It is not a fleet-wide frequency estimate.
Only bounded source-check archives were downloaded for this replay.

The [frozen evidence](ci-source-repetition-2026-10-25.json.gz) has SHA-256
`18458948c1c41d63def51f44f8e4ded7831a1ce1fae1ade1c5dd0be6a83d9e05`.
It retains the six native projections, authenticated source phase joins, controller
receipts and the separate read-only idle-publisher comparison.

Three successful main source jobs repeated an earlier successful protected-queue
aggregate at the exact same native and actual checkout revision, aggregate
identity and recorded tool cohort:

| Repeated source job | Native job seconds | Nested evaluation/build seconds | Earlier queue proof |
| --- | ---: | ---: | --- |
| finite recovery, 40168352161 | 377 | 328.421 | 40167523769 |
| finite-dev recovery, 40171167682 | 356 | 302.835 | 40167523769 |
| main after 260, 40175020315 | 300 | 252.408 | 40174527617 |
| Total | 1,033 | 883.664 | Two source revisions |

The 1,033 seconds were also measured sole-runner occupancy within their own
workflows, a lower bound on blocking time rather than a reconstructed dependency
DAG. The phase seconds are inside job occupancy; do not add them. Proof lookup,
setup, validation, retention and cleanup would still cost time in any future
reuse design, so these are repeated costs, not demonstrated savings.

The original producer's source job has a different recorded aggregate. Its
matching queue was not included in this scoped sample. The report identifies an
unseen earlier proof rather than inferring a cache miss or ineligibility.

The read-only cost report now exposes these observations automatically. It
requires a successful source job, exact actual checkout, recorded aggregate,
recorded lock/tool identities, complete successful phases within native job
occupancy and valid native timestamps. A candidate queue workflow must have
finished before the target source job started. Jobs are counted once across
retry projections; conflicting projections fail explicitly. Missing/partial
receipts, invalid clocks, unknown tools and unavailable native branch identity
remain unknown. The collector does not expand its receipt budget.

This comparison does not evaluate production reuse eligibility or infer hits.
Native runner image identity remains unknown in this projection; environment
version strings alone do not corroborate the runner cohort. Required source
checks continue to run. No source-gate bypass, cache writing or dispatch behavior
is introduced by this report extension.

## Controller observations keep transport and whole-job effects separate

| Natural controller | Complete job seconds | First-profile packet download/verify seconds | Second-profile staged verification seconds |
| --- | ---: | ---: | ---: |
| 40170942874, dispatch finite-dev | 220 | 11.388 | 0.485 |
| 40174464663, after both promotions | 231 | 21.716 | 0.680 |
| 40175426729, after 260 main | 165 | 20.993 | 0.524 |

These native receipts establish execution of shared-packet staged verification.
They do not form matched complete-job comparisons. The last two invocations
found both profiles already dispatched and did not call the publisher-busy
predicate. Their different complete-job times therefore do not demonstrate a
production speedup from the active-query change in 260.

Two additional read-only API comparisons while no publisher was active returned
idle with both methods. The old predicate used five requests and 12.845–13.320
seconds; the active-status predicate also used five requests and 2.103–2.121
seconds. Opposite orders were predeclared; only GETs were permitted. Together
with the earlier active-publisher comparison, this validates both observed lookup
outcomes and measures function cost. It does not establish hosted job savings.
No diagnostic VM or controller round was started.

## Current findings

| Work | Classification | Action |
| --- | --- | --- |
| Two-profile security-259 recovery | Completed | Both fresh and upgrade/rollback phases and promotions passed with retained images. |
| Shared decision-packet staging | Observed transport rollout; whole-job savings require measurement | Natural receipts show second-profile verification without another packet download; continue whole-job accounting. |
| Active publisher queries, 260 | Awaiting production path evidence | Queue/main/controller passed; the first natural controller did not need the changed predicate. Do not manufacture a dispatch for measurement. |
| Repeated source aggregate work | Requires design and validation | Read-only matching is implemented here; exact authority/platform/fallback rules are still proposals. Keep source checks running. |
| Automatic full retry during human admission | Requires design | Authenticate pending proposal, exact candidate inputs and retained-artifact/freshness bounds before suppressing work. An open PR alone is insufficient. |
| Installer runtime and guest transport | Requires measurement | Preserve unseeded installation, actual bootc Home Manager activation, Secure Boot, enforcing SELinux, both Nix sockets and rollback/customization acceptance. |
| Product origin receipt and zstd | Deferred adoption | Preserve failed/stopped benchmark costs and existing adoption gates; retain production product ZIP verification and default installer compression. |
| Same-build OCI export | Deferred | The locked CLI has no usable dual-output export; registry-only diagnostics do not prove this alternative. |

The original October 30 observation endpoint remains separate. Recent results
support continued work now. Automatic Cachix writing and Grype database transport
stay disabled. Historical reports and frozen samples retain their measurements.
