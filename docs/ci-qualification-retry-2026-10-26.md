# Qualification retry recovery and rollout accounting

Current follow-up to the [0.8.3 ledger](v0.8.3-release-plan.md). Preserve older
reports and the original October 30 observation endpoint. This report records
a real failure, its bounded recovery and an authenticated read-only replay;
it does not issue release or qualification authority.

The [frozen snapshot](ci-qualification-retry-2026-10-26.json.gz) has SHA-256
`3e5c5243eb95c024dc602a2c290600aa0d9956d83ef33c6d11c67349df8680c4`.
It retains four selected native run projections, exact phase origins, original
artifact digests, candidate/predecessor and qualification-context identity.
This is a focused rollout sample, not a fleet census or matched cost campaign.

## Observed failure and recovery

Main [run 40367978697](https://github.com/closure-labs/finite/actions/runs/40367978697)
at `e0b270e0b1c416fb3944193730ee0f3c0b46c19e` passed Finite fresh and
upgrade/rollback, plus Finite-dev upgrade/rollback. Finite-dev fresh failed
before ISO/guest work: the pinned Sigstore installer received HTTP 504 on four
bootstrap downloads within seven seconds. One failed-jobs retry installed
Cosign and passed Finite-dev fresh. All four VM phases therefore passed across
the two attempts, but the complete workflow still failed.

The second aggregate requested both phase artifacts with attempt suffix `2`.
Its successful upgrade artifact was produced in attempt `1`, so collection
failed. Repeating that aggregate unchanged cannot repair the missing name.
Do not rerun passing VMs to manufacture another identical artifact or promote
this failed whole workflow as reusable qualification.

The read-only replay authenticated the successful Finite-dev producers:

| Phase | Producing attempt | Native job | Artifact |
| --- | ---: | ---: | ---: |
| Fresh | 2 | 121779557615 | 12680816935 |
| Upgrade/rollback | 1 | 121751501591 | 12679100739 |

Both archives identify the same candidate and complete qualification context.
The replay downloaded only their small evidence ZIPs. It issued no aggregate
acceptance, dispatch, release decision, Nix build or VM execution.

## Repair boundaries

Authenticate each current successful phase's exact native source, job, runner,
interval and steps. Locate its single actual producing attempt, rather than a
copied check-run in a later attempt. Require the original artifact name, digest,
size, run/source binding and creation during that producer's execution. Failed,
missing, ambiguous, expired or altered evidence fails closed; no older successful
phase can replace a newly failed phase. Bound lookup to 20 attempts and 1,000
jobs/artifacts per inventory. The same logic covers a carried reusable-prepare
artifact; its existing fresh reuse verifier still runs afterward.

Stage and authenticate every required ZIP before publishing phase files.
Extract only that phase's namespaces, reject unsafe members, and do not overwrite
existing files or links. Existing candidate/predecessor, tool-context, desktop,
Secure Boot, encryption and actual Home Manager checks remain mandatory.
Qualification stays scoped to the same run and source; this is not a cache of
cross-source acceptance.

Retain each phase's original job/artifact/attempt and completion time in the
aggregate. Qualification time is the earliest phase completion; phases older
than 24 hours or dated in the future are rejected, so retrying cannot renew age. A carried
fresh phase keeps its original pristine-ISO attempt. Recovery independently
checks that fresh producer and authenticates its original ZIP before accepting
the ISO/context linkage. Legacy receipts retain their exact-attempt requirement.
Approval, security freshness, reservations, signing and publication stay separate.

## Accounting correction and rollout

GitHub assigned new check-run IDs to 20 carried completed jobs in attempt two,
while preserving their original runner, timestamps and native steps. Counting
IDs alone charged another 9,953 runner seconds. The report now retains those
IDs as aliases of the one proven execution. Different/missing identity evidence
is not collapsed, and actual reruns and failed work remain charged. This changes
accounting, not actual runtime or billed savings.

The corrected complete main run occupies 11,882 runner seconds across both
attempts. The withdrawn integration queue retains its native failure and 484
seconds. The two completed integration/retry source PR workflows occupy 457
and 484 seconds. These exact revisions remain separate cohorts. Main's source
job authenticated an enabled proof hit and occupied 56 seconds, including
3.222 seconds in lookup, but its failed whole workflow cannot contribute a new
successful whole-workflow canary sample.

Batch the tool/lock integration, bounded Cosign download spacing, Decider lock-PR
identity and this collection repair into one protected rollout. Preserve the
already approved heads; supersede them and the personal-authored lock PR only
after integration succeeds. Require the hosted pinned aggregate, both queue VM
profiles and main fresh/upgrade qualification before advancing main again.
The separate historical-provenance concurrency prototype remains unpublished
and serial in production until its own canary gate passes.
