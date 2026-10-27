# Foundation 0.4.1 first queue observations, October 27 UTC

[#291](https://github.com/closure-labs/finite/pull/291) merged at
`7b5d3e690d3efcbdf72e87fdb2ecd25831ec892f` after its
[protected queue run](https://github.com/closure-labs/finite/actions/runs/40468511341)
passed both profiles' exact local candidate boots. This combines Foundation
v0.4.1, bounded timing collection and the merged Bluefin update #294.
The [authenticated snapshot](ci-foundation-rollout-2026-10-27.json) records all
three receipt archives, with no unavailable or unmatched receipts.

## Measured intervals

The complete queue used 5,829 runner seconds. Its finite and finite-dev build/VM
jobs used 2,440 and 2,994 seconds. Each guest emitted eight valid Foundation
records and zero rejected records. Successful initialization did not exercise rollback.

| Interval / seconds | finite | finite-dev |
| --- | ---: | ---: |
| Local ISO construction | 753.4 | 815.5 |
| VM acceptance, including installation and initialization | 890.9 | 1,053.4 |
| Image build | 435.6 | 595.3 |
| Local OCI export | 184.4 | 321.0 |
| Home initialization, nested within VM acceptance | 435.1 | 451.8 |
| Home Manager realization, nested within initialization | 167.9 | 167.7 |
| Brew bootstrap, nested within initialization | 143.6 | 148.5 |
| Home Manager activation, nested within initialization | 101.8 | 113.0 |
| Profile validation, nested within initialization | 21.2 | 21.6 |

Realization ranks first among initializer children, followed by Brew bootstrap
and activation. Brew policy evaluation took only 0.64/0.87 seconds; it cannot
explain the roughly 144/149-second provisioning interval. The earlier guest
Homebrew startup check measured zero whole seconds and excludes subsequent
Foundation package provisioning. Preserve that distinction.

ISO construction remains substantial; its RPM/template/compression fractions
are still unknown. Required VM acceptance coverage is not established avoidable
work. Do not add nested totals or use guest timestamps as host critical-path
intervals. Two profiles in one queue run are not matched warm/cold pairs or a
causal savings benchmark.

## Next audits

The pinned Foundation initializer still runs one `nix build` with its existing
memory, swap, CPU and job limits. Realization includes evaluation, downloads,
builds and bounded retries. Audit existing structured Nix observations before
adding substage instrumentation; preserve command semantics and one activation.

The pinned [Brew bootstrap](https://github.com/closure-labs/foundation/blob/8ae2b6bdcca1f7c025fd9c75e7b5273cffd79de0/modules/home/commands/_assets/finite-brew-bootstrap)
checks installed policy, runs `brew bundle install --no-upgrade` when needed,
and verifies policy afterward. Automatic Brew updates are disabled. Separate
policy checks from package transport/install before proposing reuse. Preserve
unseeded fresh installs and required packages.

Activation's total does not identify a particular hook or prove Flatpak dominates.
The [Flatpak provider](https://github.com/closure-labs/foundation/blob/8ae2b6bdcca1f7c025fd9c75e7b5273cffd79de0/modules/providers/flatpak/_feature.nix)
imports nix-flatpak; Foundation's compatibility hook preserves the activation DAG.
Inspect generated hook boundaries before changing ordering or parallelism.

## Production and release gates

[Main run 40474776795](https://github.com/closure-labs/finite/actions/runs/40474776795)
finished failed after both builds, scans and attestations succeeded. Both signing
jobs independently refused admission: the candidate requires an authenticated
maintainer security decision. Signing credentials were not reached; all production
qualification and promotion jobs were skipped. No predecessor reuse miss or
production Foundation timings are observed.

The attempt used 3,369 runner seconds, including both denied signing jobs.
Security scans accounted for 584/988 seconds (1,572 total), image builds 533/707
seconds, and signing admission jobs 90/116 seconds. These are complete job costs,
not isolated download or verification costs. Retain the failed attempt. The cost
reader authenticated five compact receipts; two full scanner archives exceeded
its 8 MiB bound and were explicitly unavailable. The decision producer separately
binds those native scanner artifact digests in its immutable packet.

The source check authenticated the exact queue proof in 2.774 seconds.
[Security proposal #296](https://github.com/closure-labs/finite/pull/296), head
`38bf6e1f42a5c7a94dcad8fe32619c9b9ded6051`, proposes accepting 563 normalized
findings: finite has 21 Critical/127 High and finite-dev 22 Critical/131 High.
The complete scope also includes Medium, Low and Unknown findings. Its canonical
proposal hash and packet producer match this run and source. This verifies the
proposal's binding, not exploitability or acceptance of the findings. The human
security decision is independent of #291's code approval.

Review that decision before resuming signing. After authorized acceptance merges,
use the existing controller's native recovery path and fresh security checks;
do not rerun all successful image builds or bypass source/approval freshness.
The cancelled superseded Bluefin main retained 1,606 runner seconds and is not a
successful rollout or a savings benchmark. Do not launch extra VM rounds for
samples, weaken reuse identity, or publish based on queue-only evidence. The
[release ledger](v0.8.3-release-plan.md) retains runtime identity, final
security/audit, workstation pilot and paired release requirements.
