# Cost-report changes and image selection, October 23, 2026

The timing-reader correction in #242 passed the protected queue and merged at
`5df4addb98a69d8417210681137f3f32987c613d`. Its
[queue run](https://github.com/closure-labs/finite/actions/runs/40038537380)
selected image validation for both profiles, although its executable changes
only read native metadata and retained receipts. No VM round was selected.
The [companion record](ci-cost-selection-2026-10-23.json.gz) retains the native
job identities, timestamps and authenticated partial transport samples.

| Queue image job | Job ID | Runner seconds |
| --- | ---: | ---: |
| finite | 120705554528 | 559 |
| finite-dev | 120705554388 | 765 |
| Total | | 1324 |

The two jobs consumed 22.07 runner minutes. The developer job continued alone
for the final 207 seconds of image validation. This is a measured lower bound
on blocking work, not a reconstructed dependency DAG. These are one queue's
observations; recurring frequency, post-change savings and billing remain
unestablished. Do not extrapolate this sample into a weekly saving.

## Select source checks for the read-only observer

Explicitly classify `scripts/ci/workflow-costs.py`,
`scripts/ci/workflow_costs.py`, `scripts/ci/cost_receipts.py` and
`.github/workflows/workflow-costs.yml` with the existing source-only inputs.
They are outside the OS image and qualification input contracts. Retain the
pinned Nix/runtime aggregate, documentation, CodeQL and protected authority
checks. New helper paths retain conservative image selection.

Mixed changes still select the affected recipe or both shared-image profiles.
The independent VM selector and payload selector still require both premerge
profiles for boot or VM-harness changes. Lock changes retain dependency
comparison. Main reconciliation and unpublished-version selection can still
request images independently; a report-only push is not a blanket prohibition
on publication needed for another reason. Image and qualification identity
formats, guest behavior and installer behavior are unchanged.

Focused regressions exercise complete matrix selection for a report-only
change and report changes mixed with boot inputs. They also check actual image
and qualification hash inputs, unknown helpers, recipe selection, lock selection
and existing failure propagation. Hosted source checks and natural queue/main
selection must establish rollout before claiming the cost was removed.

## Transport comparison remains unadopted

The [existing diagnostic matrix](https://github.com/closure-labs/finite/actions/runs/40037635079)
is still running. The first four completed native samples passed correctness
for the identical 13,422,077,161-byte inventory and the pinned tool cohort.

| Phase and pair | Legacy complete seconds | Receipt complete seconds | Runner image comparison |
| --- | ---: | ---: | --- |
| Cold 1 | 426 | 237 | Both `20261012.334.1` |
| Warm 1 | 723 | 900 | Legacy `20261023.334.3`; receipt `20261012.334.1` |

The cold pair alone cannot justify adoption. Warm pair 1 is unmatched and
cannot satisfy the required five matched warm pairs, regardless of the eventual
medians. Retain it in the report; do not replace it with a more favorable run or
attribute its duration difference to the receipt implementation. The remaining
matrix jobs continue without redispatch. Complete-job times include the warm
seed, setup, transfers, hashing, retention upload and local cleanup. Producer
cost remains a separate 1741 runner seconds. OCI retention and registry cleanup
remain unobserved; production continues strict original ZIP verification.

## Natural main qualification results

[Main run 40032009520](https://github.com/closure-labs/finite/actions/runs/40032009520)
at `6ef15e7e2d2d` passed all four VM phases, including both profiles' fresh
installs and upgrade/rollback acceptance. Standard promoted. Developer's later
aggregate stopped with `Main changed release inputs; stop obsolete qualification
work` after #242 advanced main; its promotion was skipped and the overall run
failed. Retain that source-currency guard and do not resume the old candidate.
A successful VM phase alone is not successful publication.

| Profile and phase | Complete job seconds | Image acquisition | Installer preparation | ISO construction | VM acceptance | Actual home-init |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| finite fresh | 1749 | 3.892 | 22.523 | 744.032 | 795.979 | 370 |
| finite upgrade | 1534 | 2.828 | 15.230 | 560.885 | 841.412 | 306 |
| finite-dev fresh | 1522 | 3.671 | 18.062 | 551.034 | 757.672 | 320 |
| finite-dev upgrade | 1746 | 3.164 | 18.076 | 610.932 | 989.991 | 330 |

Each column is seconds. Stages are nested; do not add them to complete job costs.
These four jobs consumed 6551 runner seconds. ISO construction and VM acceptance
are the large intervals, while explicit image acquisition took less than four
seconds per phase. ISO construction includes installer-internal transfer, so
these observations cannot prove that all remaining time is Lorax computation.
Home initialization remains material, but its fetching, evaluation and
realization are not yet isolated. Required unseeded installation, bootc Home
Manager activation, Secure Boot, enforcing SELinux and both Nix sockets passed
through the existing acceptance commands. Installer-runtime reuse and guest
closure transport remain proposals; avoidable fractions are unknown.

The corrected reader joined all four native phase receipts without unmatched
rows. Two oversized security archives remain explicit coverage gaps. Upgrade
predecessor-reuse stages returned unavailable in 23.297/25.013 seconds; that does
not establish execution of the 600-second optional ZIP transfer timeout path.

No additional VM round was dispatched for this report. The seven-day assessment
endpoint remains `2026-10-30T05:01:17Z`; later revisions are separate incomplete
cohorts. Cachix writing and Grype database transport remain disabled.
