# CI rollout and governed dependency updates — October 23, 2026

The [companion record](ci-rollout-2026-10-23.json) binds observations to native
runs, attempts, source revisions, candidates, artifact hashes and available
runner/tool cohorts. These reports grant no approval or publication authority.

## Verified rollout

Finite [#231](https://github.com/closure-labs/finite/pull/231) and
[#232](https://github.com/closure-labs/finite/pull/232) passed both-profile
protected-queue VM validation and merged. Security decision
[#234](https://github.com/closure-labs/finite/pull/234) received native approval
at its exact head, passed the protected queue and merged at
`23c06c71c671106ae8ac7ea5112224c5c5d400be`.

[Production run 39931669315](https://github.com/closure-labs/finite/actions/runs/39931669315)
passed fresh security admission, signing, fresh-install and upgrade/rollback
qualification, aggregation and promotion for both profiles. Downloaded aggregate
and promotion archives match their native SHA-256 digests. Their receipts bind
that exact source and the expected candidates and build-input identities. Secure
Boot, encrypted storage and Home Manager acceptance pass in both VM lanes.

The published channel candidates are:

| Profile | Image digest |
| --- | --- |
| Standard | `sha256:75bf6f6feb87213dd6116b747551a3b410023a26e08caf6dce797d92cb26d9d3` |
| Developer | `sha256:823af0dfebb798f9f7676def8df34763e69247d5c881da93be74f2d8eeda0fbd` |

Existing published release assets and the frozen `0.8.2-dev` execution were not
modified. The guest now uses published Foundation 0.3.2; the application-sources
documentation is corrected to that immutable pin.

## Measured remaining VM costs

The [#232 queue run](https://github.com/closure-labs/finite/actions/runs/39924113610)
provides one job per profile with the new stage timers:

| Stage | Standard | Developer |
| --- | ---: | ---: |
| OS image build | 430.391 s | 628.641 s |
| Local OCI export | 183.876 s | 301.959 s |
| Installer preparation | 15.787 s | 22.030 s |
| Installer ISO construction | 737.695 s | 821.334 s |
| Complete VM acceptance | 794.435 s | 940.610 s |
| Home activation within acceptance | 342 s | 364 s |

ISO construction and export account for most of the earlier unexplained VM
time. These samples do not establish a median or net savings. The duplicate PR
image round is removed; complete PR-to-promotion cost still needs observation.
The seven-day window ends `2026-10-30T05:01:17Z`. The matched retained-OCI versus
registry comparison remains unrun, so immutable-registry verification stays in
use. Cachix writing and Grype database transport remain disabled.

A path-only decision-push routing prototype was not adopted. A newer ledger-only
run can replace an older pending runtime push in the current concurrency group;
suppressing its ordinary reconciliation without proving complete runtime
coverage can strand the update. The prototype was restored without pushing a
workflow change. A safe handoff must preserve source coverage, leases and current
authority. See [GitHub's concurrency contract](https://docs.github.com/en/actions/concepts/workflows-and-actions/concurrency).

## Dependabot #233: passing CI, ineligible submitter

[#233](https://github.com/closure-labs/finite/pull/233) at
`24265c09767aca8ad3ee745b36a7918f89ddcea6` passed source checks, both image/VM
jobs, CI gate and CodeQL. Native maintainer approval is present. Its separate
App-origin authority check rejects the Dependabot submitter for governed paths.
Toggling auto-merge cannot resolve that policy requirement.

The adopted ten-file dependency update matches #233's Git blob identities byte
for byte. The configured App submits the replacement for fresh review; approval
on the original PR is not copied. The additional preflight rejection reports the
adoption action before unsupported bots consume expensive validation. It grants
no authority and leaves the App's live role/review checks in force.

The upstream [Determinate action comparison](https://github.com/DeterminateSystems/determinate-nix-action/compare/d0c908e6cbe9f89f36ed8205a3ab6f092636916a...e847f25223456b3058e12f7fc9d777b6a6f25060)
updates the default installer tag from 3.23.1 to 3.23.2 and its pinned installer
action. It does not change Finite's guest installer source pin. The upstream
[token action comparison](https://github.com/actions/create-github-app-token/compare/bcd2ba49218906704ab6c1aa796996da409d3eb1...64ab729a6294000f5aa4a4bc0b73d1f32bc45510)
adds permission options, removes the unused team-discussions option and updates
dependencies. All declared inputs in Finite's 18 updated token steps remain
supported; every step explicitly scopes repositories. Requested permissions and
credential profiles are preserved.

Focused preflight tests cover unsupported bots, the configured App, ordinary
non-governed bot changes, missing public configuration, renamed governed paths,
moved heads and exact tree differences. Full hosted aggregate and queue checks
remain required for this dependency/host-tool change before adoption. Rollback
restores the two action pins through review; existing images and release assets
need no mutation.
