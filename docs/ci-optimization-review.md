# CI reliability and optimization review

Baseline collected September 7, 2026, for `closure-labs/finite`. The review
covers all 572 runs returned for August 8 through collection time, including
572 successful job-list queries. Much of this history predates the current
BlueBuild workflows and the repository's rename from Purplefin.

## Evidence and measurement

The sample contains 302 successful runs, 151 failures, 113 cancellations,
one startup failure and five skips. These are historical outcomes, not the
failure rate of the current implementation. Twenty-seven runs have multiple
attempts. There are 31 repeated workflow/event/source-SHA groups; schedules,
manual validation and legitimate reruns mean those groups are not automatically
wasted work.

The table below isolates runs named `Build Finite`. Times are minutes.
Wall time runs from creation to the latest job completion; initial wait runs
from creation to the first non-skipped job start. Both exclude rerun attempts
because the run creation timestamp belongs to the original attempt. Job minutes
sum non-skipped job durations for the latest attempt, including failed and
cancelled jobs; they are not billed minutes or a dollar estimate.

| Event | Runs | Failed | Cancelled | Wall median / p95 | Initial wait median / p95 | Summed job minutes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Pull request | 134 | 53 | 42 | 19.97 / 54.25 | 0.07 / 1.13 | 7,522.25 |
| Merge group | 39 | 2 | 5 | 19.22 / 32.88 | 0.07 / 1.20 | 1,882.32 |
| Push | 32 | 5 | 7 | 15.91 / 127.85 | 0.05 / 2.38 | 2,733.40 |
| Schedule | 16 | 2 | 1 | 8.32 / 204.67 | 0.07 / 79.60 | 699.82 |
| Manual dispatch | 7 | 4 | 2 | 42.90 / 50.33 | 1.04 / 33.13 | 431.48 |

Wall/wait sample sizes are respectively 124, 39, 32, 16 and 6. Percentiles use
the nearest-rank method. Initial wait includes workflow orchestration and
concurrency delays; it is not an isolated runner-capacity metric. All workflows
combined consumed 26,182.07 measured job minutes across 3,083 non-skipped jobs
with complete timestamps. Earlier attempts and jobs without timestamps are
excluded, so this is not a complete usage ledger.

Current updater names have separate outcomes: Determinate Nix has three runs,
all failed; flake inputs has four runs (one success, two failures, one cancelled);
Home Manager release advancement has three successes; Dependabot queueing has
21 successes. The current ISO and VM workflows have no runs in this sample;
older installer workflows cannot establish their reliability.

Data came from the paginated REST endpoints
`repos/closure-labs/finite/actions/runs?created=%3E%3D2026-08-08&per_page=100`
and `repos/closure-labs/finite/actions/runs/RUN_ID/jobs?per_page=100`, using the
latest attempt returned by the jobs endpoint. Reproduce collection with
`gh api --paginate`, retain creation/start/completion timestamps, and group
by workflow name and event. Do not compare the old runtime pipeline against
BlueBuild as if the workloads were equivalent.

## Confirmed causes and changes

- [August 31](https://github.com/closure-labs/finite/actions/runs/33417839486)
  and [September 7](https://github.com/closure-labs/finite/actions/runs/34136587582)
  Determinate updates failed because release lookup lacked `GH_TOKEN`.
  The resolver now receives the built-in token explicitly and uses bounded,
  authenticated GETs; local invocation can use existing `gh` authentication.
- [PR 102 validation](https://github.com/closure-labs/finite/actions/runs/34137013478)
  rejected `devenv.lock` without a final newline. Lock generation now normalizes
  final newlines before calculating changes; updater workflows validate text
  before creating a PR.
- Parent updater timeouts were 20-30 minutes, shorter than their possible child
  validation. The parent now allows 210 minutes and each child wait 180 minutes,
  covering the 5-minute selection/docs, 45-minute checks, 120-minute images and
  5-minute gate budgets, plus limited queue overhead. The parent still bounds
  total runtime if preprocessing or runner queueing takes too long.
- The release updater now distinguishes absent branches/HTTP 404 from outages.
  Only confirmed absence reports successful no-change. Downloads retry transient
  errors within a fixed budget and leave existing pins intact on failure.
- Trusted updates reuse PR or manual validation for the same branch and commit.
  Failed validation emits a direct run link and cannot enable auto-merge.
  The CI gate reports prerequisite failures without cascading missing-matrix
  errors, while still blocking the merge.
- `devenv.lock` previously took the unknown-path fallback, forcing four images
  during paired lock updates. It and the updater HTTP helper now select checks
  only; changes to `flake.lock` still compare image payload dependencies.
- Default workflow tokens for the updaters and Dependabot queue now have only
  contents-read permission. PR/merge operations retain their dedicated token.

## Current build bottleneck

The [September 7 scheduled build](https://github.com/closure-labs/finite/actions/runs/34131822698)
published and verified all four images successfully. Its logs contain 74
BuildKit `CACHED` markers and registry-cache imports. There were no recorded
`HTTP error 401` messages or Nix substitutions from `finite-os.cachix.org` in
that run. Those observations establish working container cache reuse, not a
cache hit rate or proof that the Nix cache is misconfigured.

| Profile | Job minutes | Stage payload | BlueBuild step | Final inspection |
| --- | ---: | ---: | ---: | ---: |
| Generic | 4.33 | 0.37 | 0.67 | 2.93 |
| DX generic | 5.97 | 0.45 | 0.75 | 4.27 |
| Next | 4.57 | 0.28 | 0.72 | 3.18 |
| DX next | 5.88 | 0.40 | 0.62 | 4.45 |

Final inspection accounts for about 14.83 of 20.75 aggregate image-job minutes.
It includes pulling the published image, signature verification and runtime
checks; the data does not isolate which of those dominates. Two scheduled builds
and one main push since September 6 succeeded; three builds are insufficient
for a stable performance estimate. Payload staging totals only 1.50 minutes in
the sampled run, so an artifact-sharing redesign is not the first priority.

## Ranked follow-up opportunities

These are separate changes, not claims of measured savings. Effort is relative:
small is a focused patch, medium requires workflow experiments, large changes
the release or credential architecture.

| Priority | Opportunity and evidence | Benefit / effort / risk | Acceptance criteria |
| --- | --- | --- | --- |
| P1 | Split inspection timings, then benchmark verification of the exact local build digest against the current registry pull. Inspection dominates the sampled warm build. | Reduce repeated transfer; medium; risk of validating a different image. | Compare at least five equivalent warm runs plus a cold run; verify the exact published digest, signatures and all existing checks; report transfer and runtime changes. |
| P1 | Validate a candidate digest before promoting mutable channel tags. The current action pushes before final inspection. | Prevent failed final checks from leaving a bad channel; large; changes publication semantics. | Inject a final-check failure and prove channel tags remain unchanged; test concurrent publication, signature verification and promotion recovery. |
| P2 | Measure Nix substitution and evaluation separately; compare guarded cache warming against current behavior. Current runtime checks took 3.07 minutes and payload staging repeated per profile. | Reduce cold setup/evaluation; medium; cache trust and storage costs. | Record cache sources, misses, download bytes and closure identity; benchmark cold/warm cases; retain clean-cache success and prevent untrusted cache writers. |
| P2 | Add per-job queue-delay measurement before considering runners or concurrency changes. Historical scheduled initial wait p95 was 79.60 minutes, but current PR initial waits are not proven capacity bottlenecks. | Target real queue delays; small measurement, medium remediation; concurrency can change publishing order. | Distinguish dependency wait from runner queueing; preserve serialized publication, cancelled obsolete PR runs and full scheduled checks. |
| P2 | Consolidate common updater preflight/reporting only after comparing all three updater flows. They repeat checkout, credential setup and PR operations. | Reduce configuration drift; medium; over-generalization can obscure differing file allowlists. | One shared implementation with explicit inputs, unchanged source-specific outputs, and tests for each updater's allowed files and credentials. |
| P2 | Assess replacing the dedicated automation token with a short-lived GitHub App token. Its current credential type and expiry are not established by the source. | Improve credential lifecycle; medium; external installation and permission changes. | Document required repositories/permissions; prove token expiry, PR CI triggering and merge-queue behavior in a controlled trial. |
| P3 | Audit overlapping update PRs and repeated validation by exact revision and payload identity. Thirty-one repeated groups include legitimate schedules and reruns. | Reduce redundant work; medium; skipping necessary checks. | Categorize repeats before changing scheduling; no cross-revision reuse, and all required merge-group checks still run. |
| P3 | Exercise current ISO/VM workflows and define release-evidence retention. ISO artifacts currently expire after seven days; current workflow coverage is absent in the sample. | Improve release reproducibility; medium; storage and test cost. | Complete a digest-verified ISO/VM run; retain release digest/signature/checksum records through the documented support period. |

The review follows GitHub guidance on
[least privilege and immutable action references](https://docs.github.com/en/actions/reference/security/secure-use),
[cache scope and trust boundaries](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching),
and [workflow reuse](https://docs.github.com/en/actions/concepts/workflows-and-actions/reusing-workflow-configurations).
Existing pinned actions, conservative selection fallback, signing, and protected
merges remain part of the design. No new paid runners or monitoring service is
required for the immediate fixes.

## Validation and rollout

Hermetic tests exercise credential absence, malformed releases, failed and empty
downloads, retry limits, rate-limit budgets, lock normalization, unchanged
updates, upstream absence versus outages, validation reuse and failure gates.
Run `nix develop --accept-flake-config --command nix build --accept-flake-config --no-link .#ci-checks`.
Python analysis and test commands should also run inside `nix develop`.

After integration, dispatch fresh updater runs against the fixed main revision;
rerunning an old failed run executes its old workflow revision. Let normal
flake-update automation refresh PR 102. Confirm source resolution, generated
text checks, child validation and merge protection before comparing subsequent
runs to this baseline. No post-integration performance improvement has yet been
measured.
