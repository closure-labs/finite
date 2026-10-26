# Recent rollout completion and remaining costs, October 26 UTC

The #283 integration milestone passed production: both profiles completed fresh
install, upgrade/rollback, authenticated aggregation and promotion in
[main 40400596391](https://github.com/closure-labs/finite/actions/runs/40400596391)
at `774c3ebab68ce1ec29ff97e66eddafb48a57fdc3`. Both protected-queue VM profiles
also passed. #279 was closed as superseded after its lock bytes were integrated;
Foundation remains v0.3.3. This closes D1's integration milestone, not stable
0.8.3 acceptance.

The compressed [evidence](ci-recent-rollout-2026-10-26.json.gz) contains bounded
native cost observations and the digest-verified qualification/promotion JSON
members. Both qualification records accept the same source revision and bind
Secure Boot, encrypted root, candidate, predecessor and build identity. Artifact
IDs are 12693260181 and 12692293323 for qualification, and 12693130584 and
12693276373 for promotion. Archive sizes/digests and original document bindings
are retained. Successful development promotion does not replace the future stable
freeze, stable-predecessor tests or workstation pilot.

## Scoped cost ranking

These are five named recent natural runs, not a complete fleet or seven-day
window. Source revisions and events remain separate in the evidence. The sum of
native unique-job occupancy and grouped costs both equals 17,405 seconds. Failed
work remains charged. No extra VM round was dispatched for this sample.

| Run / event | Known runner seconds | Outcome |
| --- | ---: | --- |
| [#283 protected queue](https://github.com/closure-labs/finite/actions/runs/40392230142) / merge group | 5,534 | Success |
| [#283 main](https://github.com/closure-labs/finite/actions/runs/40400596391) / push | 11,046 | Success |
| [#284 main](https://github.com/closure-labs/finite/actions/runs/40412281994) / push | 185 | Success; no images selected |
| [#284 controller](https://github.com/closure-labs/finite/actions/runs/40412595371) / completion callback | 187 | Success; serial historical reads |
| [#285 original source](https://github.com/closure-labs/finite/actions/runs/40413811998) / pull request | 453 | Failed obsolete graph assertion; retained as failed cost |

| Recurring work in this sample | Observed jobs | Native runner seconds | Next action |
| --- | ---: | ---: | --- |
| Main fresh and upgrade/rollback qualification | 4 | 7,677 | Investigate predecessor reuse misses and candidate-independent runtime boundary |
| Queue image build/export/installation validation | 2 | 5,123 | Preserve exact queue coverage; measure export/runtime work before cross-event image reuse |
| Main fresh security | 2 | 1,499 | Preserve fresh admission; inventory reuse requires authenticated exact products |
| Source checks across queue, two mains and failed PR | 4 | 914 | Enabled exact queue-proof hits observed; retain full PR/queue checks |
| Serial decision reconciliation | 1 | 187 | Native four-worker complete-job canary still pending |
| Standalone publication preflight | 2 | 108 | Consolidated in #285; net rollout savings still pending |

The role collector conservatively labels the two historical preflight and two
attestation jobs unknown; the preflight row above uses their exact native job
names. Remaining native occupancy includes build, attestation, signing,
preparation, aggregation, promotion, selection, documentation and gates. The
ranking is scoped runner cost and sample frequency. Exact dependency critical-path
contributions remain unknown; sole-runner occupancy is a lower bound within one
workflow, not a reconstructed DAG. The slowest development upgrade job has 204
sole-runner seconds; both old preflight jobs overlap other runners and have zero
sole-runner seconds. Their removal cannot be claimed as 108 seconds lower elapsed
workflow time.

Main qualification contains 2,722.501 measured ISO-construction seconds and
4,185.925 VM-acceptance seconds. Guest initialization totals 1,790 seconds nested
inside VM acceptance; do not add it to the job or VM totals. Both predecessor ISO
lookups were eligible misses, taking 20.415 and 16.089 seconds. The finite native
job log says only `No compatible retained predecessor ISO found`; rejected
candidate/context details are currently swallowed by the bounded reader. Do not
attribute these misses to network timeouts or a specific input change. A useful
next observability change is bounded miss-reason counters before changing reuse
eligibility.

Nine of eleven selected main cost archives were within the reader's bound. The
two full security archives were size-ineligible (33,279,528 and 43,535,908 bytes);
their separate compact timing receipts were read. No receipt was unmatched.
Full security-document coverage is therefore unavailable in this cost projection;
it is not zero-cost work or a fresh security verdict. Other named runs read all
selected cost archives. Unknown reuse identity remains unknown rather than
becoming a cache miss.

## Source and controller follow-through

Main #283 used an authenticated exact queue proof in a 91-second source job;
lookup took 2.321 seconds. Main #284 did the same in 68 seconds, with a 2.874-second
lookup. Both whole workflows passed and neither consumer evaluated or built the
aggregate. Each retains its own source/tool identity; these different revisions are not a
matched speedup campaign.
The #283 queue producer source job occupied 375 seconds. The failed #285 source
attempt occupied 380 seconds and still ran its full checks; main-proof reuse does
not bypass ordinary PR validation.

The native #284 serial controller occupied 187 seconds. Reconciliation itself
used 127.965 seconds, including 92.208 seconds of live authority checks and
22.416 seconds downloading the packet once. The second profile verified staged
products in 0.684 seconds. Its immutable history-worker receipt records one;
there is still no hosted four-worker result. The replay improvement in the
[prototype report](ci-history-provenance-2026-10-26.md) remains replay evidence.

The #285 graph change retains security, attestation, signing and final live
promotion guards. Its first hosted failure was an outdated graph contract,
corrected at `a4b4ecb397e9be51ab0d576f218a13496802a5ec`; protected rollout remains
pending. Its native installer log confirms FlakeHub authentication was skipped.

## Next bounded work

1. Complete #285's corrected aggregate, protected queue and natural main rollout.
   Measure the consolidated prepare job and whole publication, preserving both
   profiles' fresh/upgrade evidence.
2. Observe a bounded four-worker historical-read controller with the same ledger,
   packet and tool cohort, then return to one before deciding ongoing adoption.
3. Add bounded predecessor-ISO miss reasons without relaxing origin, integrity,
   exact generation-context or acceptance checks. Use natural upgrade runs.
4. Keep runtime reuse blocked on complete installer/RPM/template/certificate
   identity and candidate-specific injection. Add Foundation timings before guest
   closure transport. Compression still needs matching released cohorts.
5. Finish repository/release-authority audits against the eventual frozen source,
   then prepare stable qualification and the operator-authorized pilot.

Original release-packet transport remains in production: its prior origin-receipt
prototype failed adoption and is deferred under O6. Do not reopen that campaign
without a materially different measured design. Preserve October 30 05:01:17 UTC
as the original complete-window endpoint while using these recent runs now.
