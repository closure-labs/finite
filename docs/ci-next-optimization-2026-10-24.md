# Next CI optimization evidence, October 24, 2026 UTC

The reporting changes in [#245](https://github.com/closure-labs/finite/pull/245)
and [#244](https://github.com/closure-labs/finite/pull/244) merged at
`80721c62bc3a7362302ccf960fe2dcd5fabe6f86` and
`283496ca76683d5183c06b74ecb0bc85e4b4edc7`, respectively.
The [evidence snapshot](ci-next-optimization-2026-10-24.json.gz) retains the
complete transport comparison and a bounded investigation of existing
qualification logs. Earlier reports and their original measurements remain
unchanged. This report supersedes their incomplete transport experiment status.

## Complete transport result

The [consumer run](https://github.com/closure-labs/finite/actions/runs/40037635079)
completed all twelve jobs at source
`6ef15e7e2d2d7eeca79cfc4edf0d62f9d416b6ed`. Correctness passed for all twelve;
the five warm pairs and one cold pair are complete. Warm pairs 1, 3 and 4 have
different hosted runner images. Their tool versions match, but the complete
runner/tool cohorts do not.

| Observed complete-job cost | Legacy | Origin receipt |
| --- | ---: | ---: |
| Warm median, seconds | 759 | 900 |
| Cold pair, seconds | 426 | 237 |

Warm medians save **-141 seconds**, failing both the minimum 30 seconds and
10 percent improvement requirements. Cold receipt/legacy cost is 0.5563,
within its 10 percent regression bound. Unmatched warm cohorts independently
fail the adoption gate. These descriptive medians do not establish a causal
regression; there are no replacement runs to select a better result.

Native consumer occupancy totals **10971 runner seconds**. The separate
[diagnostic producer](https://github.com/closure-labs/finite/actions/runs/40034048900)
costs **1741 runner seconds**, including original-source authentication and
diagnostic upload. Complete-job costs include setup, hashing, native retention
uploads and local cleanup. Configured seven-day native logical artifact
byte-days are retained in the snapshot; actual storage duration, deduplication,
registry billing and eventual OCI deletion cost remain unknown.

The result is **retain the legacy original-ZIP production path**. The receipt
prototype remains available for diagnostics; no production caller enables it.
The experiment used a new packet containing the same authenticated two-profile
products. Existing decisions, frozen executions and published assets were not
modified. The collector is pinned to #244 head
`475397f2ec768eb1df2062d4547f500861eb1919`; its script and report hashes are
retained alongside the original pinned experiment report.

## Avoid obsolete publication work earlier

One natural [main rollout](https://github.com/closure-labs/finite/actions/runs/40032009520)
passed both profiles' fresh-install and upgrade/rollback phases, costing
6551 runner seconds across those four jobs. Standard promotion succeeded.
The developer qualification aggregate later rejected changed main inputs.
Successful VM acceptance does not override source-current publication checks.
Not all of this work could have been avoided by an earlier preflight: main can
advance while a valid job is already running.

The next change reuses the existing production eligibility launcher after Nix
setup in image and security jobs. It checks again immediately before image
build and inventory work, covering a main advance during preparation. Obsolete
sources fail before subsequent expensive stages. Validation images and branch
diagnostics retain their existing eligibility boundaries. Proven documentation
advances still use the existing stable-main ancestry rule. Final signing,
qualification and promotion checks remain independently required.

Batch related CI changes into one reviewed PR to reduce main publication churn.
The new checks introduce metadata and pinned-shell setup overhead; net savings
and obsolete-run frequency require naturally occurring rollout evidence.

## Retain the Nix breakdown

The [unchanged baseline ranking](ci-cost-roles-2026-10-24.md) identifies
373 source aggregate jobs, 30.06 runner hours and 28.77 known sole-runner hours.
Those historical values do not include the later rollout.

The existing aggregate still evaluates once, releases its evaluator and builds
only the exact resulting derivation. Retain bounded evaluation/build receipts
with per-attempt statuses and duration, including failures and retry waits.
An unstarted build has no phase. An interrupted setup has an unknown duration;
unknown values are never replaced with zero. Cache keys/hit outputs, setup
duration, runner image, executable identities and lock hashes are retained for
14 days in a small native `source-checks-RUN-ATTEMPT` artifact.

The read-only collector authenticates that artifact and joins its exact
run/source/attempt to the original checks job. Reused jobs in later attempts
are not charged again. Candidate and product-reuse fields remain unknown.
PR native head and executed merge checkout revisions are retained separately.
Stage intervals are nested in native job occupancy and are not added to it.
Native setup/post-job step durations remain available separately; a setup
total does not isolate restore, installation or post-job save cost.

No new cache, evaluator or guest behavior is enabled by these observations.
Use natural runs to compare evaluation, realization, setup and post-job cache
cost before changing the cache policy. Local aggregate builds are unnecessary;
hosted pinned `.#ci-checks` supplies the full executable verification.

## ISO and initializer investigation

The successful [standard fresh-install job](https://github.com/closure-labs/finite/actions/runs/40032009520/job/120697315283)
retains a 744.032-second `iso-build` stage. Its existing native log separates
the following internal marker intervals:

| Nested ISO interval | Seconds |
| --- | ---: |
| Lorax metadata, package install, post-install and cleanup | 323.757 |
| Runtime image creation | 264.695 |
| Initramfs rebuild | 85.721 |
| Output tree and handoff | 12.407 |
| Internal candidate OCI copy | 23.162 |
| Final assembly, checksums and return | 33.316 |

The first four intervals total about 687 seconds. Internal candidate transfer
is a smaller measured target in this job. These are marker-to-marker wall
intervals from one job, including intervening work and possible log buffering.
They do not prove all Lorax work can be reused. Any installer-runtime proposal
must first identify candidate-dependent templates, hooks, certificate, package
inputs and immutable reuse identity, then retain both profiles' full fresh and
upgrade/rollback qualification. No installer behavior changes here.

The same job's actual initializer took 370 seconds. Its existing log gives:

| Nested initializer interval | Seconds |
| --- | ---: |
| Nix source acquisition, evaluation and realization | 211.584 |
| Homebrew provisioning inside the initializer | 53.076 |
| Actual Home Manager activation | 105.283 |

The activation interval itself contains a 103.616-second Flatpak service wait.
Do not add it again to the parent. The earlier guest `homebrew-setup` stage
checks shared startup; Foundation's initializer also provisions selected tools
before activating. The source identified by the installed metadata at pinned
Foundation revision `235c34d7e507f00c2df6b0102bcdb54a4c04c5e2` follows this order.
Existing logs show source fetches, substitutions and local builds; they do not
isolate exact fetch/evaluation/realization fractions. The whole initializer
cannot be treated as avoidable Nix transport. Preserve real bootc activation,
configuration checks and unseeded fresh-install coverage.

## Current decisions

| Work | Status | Next evidence |
| --- | --- | --- |
| Report-only image selection and native role correction | Completed | [Selection report](ci-cost-selection-2026-10-23.md), [role restatement](ci-cost-roles-2026-10-24.md) |
| Transport accounting and experiment | Completed | Twelve correct samples; adoption failed, retain legacy |
| Earlier obsolete-source checks | Awaiting rollout evidence | Observe natural obsolete/current main jobs and preflight overhead |
| Retained Nix phase/setup observations | Awaiting rollout evidence | Separate recurring fractions on natural source jobs |
| Installer-runtime reuse | Requires measurement | Prove immutable candidate-independent inputs before a behavior pilot |
| Guest closure transport | Requires measurement | Isolate Nix fractions; Homebrew and Flatpak remain independent |
| Cachix writing and Grype database transport | Deferred | Remain disabled |
| Same-build retained local OCI verification | Deferred | Exact same-build export required; registry-only diagnostics are insufficient |

The seven-day assessment endpoint remains **October 30, 05:01:17 UTC**.
It is incomplete. Later cohorts remain separate from the original VM-tool
rollout; none of the new instrumentation establishes measured savings yet.
