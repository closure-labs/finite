# Inventory and qualification reuse timing experiments

The owner requested separate hosted tests of inventory reuse and whole-qualification reuse. Neither experiment changes production defaults or publishes an image. Measure standard Finite (`bluefin-generic`) and Finite Dev (`bluefin-dx-generic`) separately; the retired Next variants receive no builds, native scans or VM tests.

## New OS baseline only

The owner's latest instruction supersedes the earlier proposed frozen old-OS comparison. First complete fresh hosted builds, native security, signatures and fresh-install plus upgrade/rollback qualification for the two active variants with restored upstream kernels/modules. Select only a successful producer of those new OS changes for both experiments; do not dispatch benchmarks against earlier replacement-kernel images. The baseline records the exact new candidate, predecessor, source, build identity and qualification context.

## Inventory comparison

Run `Benchmark native security reuse` with `mode=inventory-only`. Three baseline/reuse pairs authenticate the same immutable signed native origin; each reader starts without a transported DB and performs a fresh DB update, coverage check, vulnerability scan and current policy evaluation. The strict comparison requires the same source, tool versions, DB/provider snapshot, runner-image cohort and semantic policy output. It reports complete job and phase timings, including inventory download/authentication costs. DB seeding is skipped entirely.

## Whole-qualification comparison

Run `Benchmark whole qualification reuse` against the same explicit successful producer. Three independent restore jobs use the real production context and reuse helper; separate aggregate jobs authenticate each exact benchmark handoff and rerun production acceptance/desktop validation. Matching candidate, predecessor, build/source identity, current firmware/tools/test context and the original 24-hour deadline remain mandatory.

Compare both complete reused jobs, their queue/barrier gaps, total runner time and elapsed critical path with the original producer's prepare, fresh, upgrade and aggregate jobs. The original VM jobs are an observed baseline, not a new controlled set of three VM reruns. Fresh security is a separate mandatory production stage and is not skipped or credited as a reuse saving. Diagnostic artifacts cannot authorize publication.

## Evidence and decisions

Retain small authenticated reports for every attempt, including failures or ineligible context. Measure complete costs before considering defaults. Do not interpret a failed eligibility check as a successful timing sample, or an incomplete cohort as adoption evidence. Native inventories, images, databases and VM/ISO work stay on GitHub-hosted runners; local collection is limited to bounded receipt and timing metadata.
