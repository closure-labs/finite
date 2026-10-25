# Recovery cost attribution, October 25 UTC

The [retained-candidate recovery](https://github.com/closure-labs/finite/actions/runs/40141685422)
at `70dcfb1a07d6c7561f99fca7dd378b4dd7f533cc` passed signing, fresh-install and
upgrade/rollback qualification, aggregation and promotion for `finite`.
Security revalidated authenticated, still-fresh native evidence from the original
producer; it did not perform a new vulnerability scan. The separate `finite-dev`
recovery was still running when this observation was collected.

## Copied evidence is not newly executed work

The security job occupied 111 runner seconds. Its compact cost artifact contains
510.951 seconds of scanner phases copied from the original producer. The earlier
reporter authenticated that artifact's current run/source binding and incorrectly
assigned those historical phases to the receiving job. The native job occupancy
was correct; the stage ranking and inventory-reuse observation were misleading.

The reporter now retains these unbound phases and their inventory flag under
`securityTimingAttribution`, with unknown attribution. It excludes them from
current stage rankings and leaves current inventory reuse unknown. A successful
revalidation step can also fall back to scanning when evidence is unavailable,
so neither step success nor a plausible duration establishes phase provenance.
This conservative treatment applies to legacy resumed receipts until their
actual timing producer can be established. Ordinary newly scanned jobs retain
their phase detail. Invalid or conflicting receipts still fail validation.

The [authenticated replay](ci-recovery-cost-attribution-2026-10-25.json.gz)
preserves native run/job identities, artifact inventories/digests, original
unattributed phases and the corrected report. Its SHA-256 is
`3b44f7701fb341ff9ce2ad9f8d40b5876d7bbd05318800c413f30684673b52cf`. The complete workflow remains
4,220 runner seconds before and after the correction, with unique native jobs
and grouped cost conservation. The copied 510.951 seconds are neither new work
nor a measured saving. Earlier frozen reports and measurements remain unchanged.

## Production observations and remaining targets

Both production VM phases executed the early usable-KVM check: API version 12,
an empty VM successfully created and closed, and no probe errors. Both hosts
reported four effective CPUs and approximately 16 GiB RAM. Their CPU models
differed: AMD EPYC 7763 for fresh install and Intel Xeon Platinum 8370C for upgrade.
The guest remains two vCPUs and 4 GiB with the existing acceptance requirements.

| Work | Measured seconds | Interpretation |
| --- | ---: | --- |
| Complete source checks | 392 | Includes 273.239 seconds evaluating and 66.511 seconds building the pinned aggregate |
| Complete fresh phase | 1,561 | Includes ISO construction, VM acceptance, setup and retention |
| Complete upgrade phase | 1,630 | Includes a predecessor-ISO reuse miss, construction and upgrade/rollback acceptance |
| ISO construction, both phases | 1,396.093 | Nested in the phase jobs; Docker client CPU excludes daemon work |
| Guest initialization, both phases | 616 | Nested in VM acceptance; actual Home Manager activation remains required |

The two complete VM phases account for 75.6 percent of this workflow's runner
occupancy. ISO construction, guest initialization and repeated source evaluation
remain concrete targets. A larger guest allocation is still an experiment
proposal: CPU models and runner images must be considered before claiming a
matched speedup. No allocation, installer or transport behavior changes here.

Native startup metadata still reports `20261012.334.1` while receipt environment
metadata reports `20261023.334.3` for both phase jobs. The official later image
release remained a prerelease when checked. Controlled trials remain paused;
the stopped plan gains no replacement samples. Automatic Cachix writing and
Grype database transport remain disabled. No additional VM or local Nix build
was used to obtain this evidence.
