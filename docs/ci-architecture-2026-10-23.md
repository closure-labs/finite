# CI architecture review, October 23, 2026

Status: proposed changes; hosted validation and the seven-day observation are
pending. The [machine-readable record](ci-architecture-2026-10-23.json) binds the
measurements to native runs, attempts, source revisions, candidates, profiles,
artifact hashes and available runner/tool identities. It grants no authority.

The largest confirmed duplication is an entire disposable OS build/install round
on PR updates, followed by another round in the protected merge queue. In
[PR #230](https://github.com/closure-labs/finite/pull/230), the two PR image jobs
occupied 4,811 runner-seconds (80.2 runner-minutes). Their queue counterparts
occupied 4,813 seconds. These are four observed jobs, one per event/profile;
they are not a median, billed cost, or a forecast of rollout savings.

| Event/profile | Whole image job | VM step | Home activation | VM time outside existing stage timers |
| --- | ---: | ---: | ---: | ---: |
| [PR standard](https://github.com/closure-labs/finite/actions/runs/39900947347/job/120244000085) | 1,970 s | 1,440 s | 306 s | 805 s |
| [PR developer](https://github.com/closure-labs/finite/actions/runs/39900947347/job/120243999964) | 2,841 s | 2,088 s | 358 s | 1,170 s |
| [Queue standard](https://github.com/closure-labs/finite/actions/runs/39905914342/job/120259627955) | 2,187 s | 1,615 s | 318 s | 922 s |
| [Queue developer](https://github.com/closure-labs/finite/actions/runs/39905914342/job/120259627931) | 2,626 s | 1,896 s | 320 s | 1,102 s |

The VM residual subtracts installation, SSH readiness, boot contracts and Home
Manager activation from the native VM step. It includes OCI export, installer
preparation, ISO creation and cleanup. Historical receipts cannot attribute that
residual more precisely. New stage timers cover export, installer preparation,
ISO construction and the complete acceptance command, including failure status.
Home Manager download tuning alone cannot remove the larger residual.

## Give each validation boundary a distinct purpose

| Boundary | Required proof | Credentials and authority |
| --- | --- | --- |
| PR update | Documentation, selected full Nix/runtime aggregate, profile selection and early governed-tree validation | Read-only; native App-origin maintainer authority remains required |
| Protected merge queue | Repeat source checks on the assembled revision, build selected OS candidates and run both-profile VM acceptance when selected | Read-only image transport; local receipts remain validation-only |
| Trusted main | Build/sign the candidate, fresh security admission, signed fresh-install and upgrade/rollback qualification before promotion | Existing protected signing, approval and publication checks |
| Recovery | Resume the recorded candidate only when source, identity and authority remain valid | No substitute rebuild, retag or published-asset mutation |

The native [main ruleset](https://github.com/closure-labs/finite/rules/20912451)
was independently read through GitHub Fetch. It is active, has no bypass actors,
requires the merge queue, and binds `CI gate` and `Maintainer decision authority`
to their respective GitHub Apps. The proposal removes ordinary PR image jobs;
the gate still rejects absent source checks, malformed selections, omitted VM
profiles, skipped queue images and premerge publication. Unknown events fail.
The tradeoff is that OS integration failures surface in the queue, after source
review. Every existing premerge OS acceptance case still runs before merge.

## Use Nix and devenv at their actual boundaries

The devenv check task previously evaluated the root flake to obtain a shell
launcher, which then evaluated the same root to select the aggregate. The
launcher now comes from the existing lightweight locked tool entry point. A
single root evaluation returns the aggregate derivation and its complete proof
inventory; its process exits before builders start. Standard flake-output
validation and proof existence/closure limits remain enforced afterward.
Regression fixtures reject empty, duplicate or unsafe inventories, invalid
derivations, failed builds, invalid standard outputs and missing/oversized proofs.

Lock validation also uses the lightweight entry. The weekly lock updater still
uses the exact flake-provided devenv package and transitive graph. Replacing that
with nixpkgs.devenv would change the tool being tested and is not justified.
The existing SecretSpec credential isolation applies before tool realization.
No automatic Cachix writer or Grype database transport is enabled.

Foundation builds Home Manager configurations without activating them. Finite's
guest acceptance proves activation on the actual bootc OS, including persistence,
SELinux, Secure Boot and the Nix sockets. Replacing this with a devenv container
or a NixOS VM would test a different system. Seeding guest closures could reduce
downloads, but would remove cold-download coverage from that lane; it needs a
separate measured design preserving unseeded signed fresh-install acceptance.

Foundation's feature-push and PR triggers start overlapping full profile builds.
A separate Foundation workflow change limits push CI to main while retaining
PR, merge-group, manual and exact-source reusable release checks. Reusing main CI
for tag preparation remains a proposal: it needs exact workflow/run/attempt
provenance, latest-attempt handling and fallback validation. A matching check
name or old successful conclusion is insufficient. Full tag CI stays in place.

The Finite download wrapper also had the mixed-diagnostic retry defect found in
Foundation: an earlier transient warning could hide a later positive signal or
wrapper exit status. It now retries only ordinary exit 1 and treats kill/OOM
diagnostics as terminal. Regression subprocesses exercise both cases.

## Adoption and rollback

Keep this change in draft until its hosted source checks and retained evidence
are reviewed. Verify that PR image jobs are skipped, then require the protected
queue's complete two-profile image/VM validation and normal main qualification.
The approved Foundation adoption in
[PR #231](https://github.com/closure-labs/finite/pull/231) proceeds at its existing
head; this proposal does not restart it or replace its candidate.

The [cost observer](https://github.com/closure-labs/finite/actions/runs/39912011060)
retains the exact 14-day baseline and the observation beginning
`2026-10-23T05:01:17Z`. The seven-day window ends October 30 at that time. Include
failed/cancelled jobs, attempts and queue delays when comparing the complete
PR-to-promotion path. Do not count the removed PR job duration as realized net
savings until queue/main outcomes and retries are observed.

The retained-export versus immutable-registry comparison still lacks five warm
pairs and one cold pair per profile. Registry verification remains in use; its
manifest/config/layer association, platform, signature and security checks stay
required. The original 10-percent/30-second warm and 10-percent cold criteria
still apply to that alternative. New stage timers help locate work worth testing.

Rollback restores the previous PR image condition and gate expectations together
through a reviewed change; queue and main proofs remain required throughout.
The lightweight launcher can revert independently without changing proof content.
No rollback requires deleting personal configuration, purging caches, changing
frozen `0.8.2-dev`, or modifying existing published release assets.

Reference guidance: [devenv tasks](https://devenv.sh/tasks/),
[devenv in GitHub Actions](https://devenv.sh/integrations/github-actions/),
[Home Manager](https://nix-community.github.io/home-manager/) and
[GitHub merge queues](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/configuring-pull-request-merges/managing-a-merge-queue).
