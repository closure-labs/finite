# Foundation 0.4.1 production qualification, October 27 UTC

The [approved-source scheduled run](https://github.com/closure-labs/finite/actions/runs/40521333174)
completed successfully at source `3125b26c6087b9394f8ff42a3120fd03a596289e`.
Both profiles passed fresh-install and upgrade/rollback phases, independent
aggregates and promotions. The [compressed evidence](ci-foundation-production-2026-10-27.json.gz)
retains native job accounting, bounded phase receipts and verified qualification/
promotion archive digests. Both acceptance records confirm Secure Boot,
encrypted root and the exact source/candidate binding. This closes the ordinary
Foundation v0.4.1 rollout; stable release acceptance remains separate.

## Actual predecessor misses

Both upgrade phases fell back safely after an ISO reuse miss. Each examined
20 historical runs. Finite found one generation-input mismatch and 19 runs
without qualification artifacts; finite-dev additionally rejected a different
candidate/profile artifact, leaving 18 without qualification artifacts.
These are per-run/artifact lookup counters, not independent VM attempts.

Both generation mismatch samples identify the same six paths:

- `.github/workflows/qualification.yml`
- `scripts/bluebuild/guest-timings.py`
- `scripts/bluebuild/qualification-context.py`
- `scripts/bluebuild/qualify.sh`
- `scripts/bluebuild/vm-acceptance.sh`
- `scripts/ci/foundation_timings.py`

The bounded observations authenticate job/profile/source/attempt and retain
untruncated paths. They explain this rollout's misses; they do not justify weaker
reuse keys. Lookup cost was 11.75/12.52 seconds. Both fresh fallback ISOs installed
and completed upgrade and rollback acceptance. No transfer timeout was observed.

## Production initializer and recurring cost

| Fresh initialization / seconds | finite | finite-dev |
| --- | ---: | ---: |
| Complete initialization | 427.3 | 492.0 |
| Home Manager realization | 157.6 | 177.5 |
| Brew bootstrap | 141.8 | 156.3 |
| Activation | 103.8 | 133.9 |
| Profile validation | 23.3 | 23.9 |
| Brew policy evaluation | 0.76 | 0.42 |

Each fresh guest emitted eight valid records and zero rejected records.
Upgrade initialization used its older predecessor helper and emitted no Foundation
records; those observations remain unknown. Native acceptance still checked the
actual upgraded Home Manager state and preserved customization. Nested parent
and child intervals overlap; never add them to runner occupancy or infer exact
host critical-path contributions from guest timestamps.

The complete scheduled run used 11,336 runner seconds. Qualification phases used
7,527 (about 66 percent): fresh 3,697 and upgrade 3,830. Their ISO construction
stages totaled 2,695.579 seconds, nested inside those jobs. Security scans used
1,634 seconds, builds 848, source checks 386 and attestations 161. Every native
job is counted once; failed historical attempts remain in their earlier reports.
Cost receipt coverage is nine authenticated compact archives out of 11 selected;
two full scan ZIPs exceeded the bound. Four separate qualification/promotion
archives were also downloaded and authenticated, without downloading ISO products.

Realization and Brew remain the largest measured initializer child intervals.
ISO construction and security are also substantial recurring audit targets.
This is an observed ranking, not avoidable-cost estimates or matched performance
evidence. Preserve the complete coverage and original October 30 observation
endpoint; use these recent runs for ongoing decisions.

## Next work and release boundary

1. Inspect structured Nix observations and Brew policy/install boundaries before
   adding substage instrumentation; preserve one initialization and activation.
2. Retain the installer runtime audit: candidate-specific post-scripts enter before
   compression. No compressed runtime reuse until complete independent inputs and
   a valid injection boundary are proven.
3. Audit fresh scanner inventory/database/scan work before proposing reuse; live
   admission, scan freshness and signed candidate identity remain independent.
4. Audit the controller dispatch observed after scheduled publication, including
   its requested profile/origin and current channel state, before calling it
   redundant or cancelling it. A native decision dispatch is not automatically
   proof that the scheduled rollout reused artifacts.
5. Finish final source/security audits and the operator workstation pilot before
   stable 0.8.3 freeze, final qualification and an immutable paired release proposal.

#298's cost-attribution correction is separately approved and queued; its source
change does not alter guest/installer behavior. Existing published development
assets and reservations remain untouched. The
[release ledger](v0.8.3-release-plan.md) retains all remaining acceptance gates.
