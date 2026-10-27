# Attestation accounting and approved rollout, October 27 UTC

The human security decision [#296](https://github.com/closure-labs/finite/pull/296)
merged as `3125b26c6087b9394f8ff42a3120fd03a596289e`; its approved head is
`38bf6e1f42a5c7a94dcad8fe32619c9b9ded6051`. The
[first timing report](ci-foundation-rollout-2026-10-27.md) merged in #297.
Its earlier signing denial remains a historical failed attempt, not a new failure.

The [scheduled approved-source run](https://github.com/closure-labs/finite/actions/runs/40521333174)
has passed both builds, scans, attestations, signing and qualification preparation.
All four fresh/upgrade phase jobs are running at this snapshot. Their outcome,
production Foundation timings, predecessor diagnostics, aggregates and promotions
remain unknown until authenticated native receipts are retained.

The report-source [main run](https://github.com/closure-labs/finite/actions/runs/40519353101)
stopped when its source became obsolete. The security-decision merge's
[push run](https://github.com/closure-labs/finite/actions/runs/40520989425)
was cancelled before jobs started. Retain both records beside the active schedule;
do not attribute that scheduled run to controller recovery or infer artifact reuse.

## Corrected cost role

Native jobs `Publish (finite) / attest / attest` and
`Publish (finite-dev) / attest / attest` previously fell into the unknown role.
The read-only collector now recognizes the exact `attest` terminal component
through its existing role matcher, retaining separate profiles, events and sources.
Unrecognized names continue to report unknown. This does not change CI execution,
credentials, approval, signing, artifact validation or publication ordering.

On failed admission run 40474776795, the two attestation jobs used 87 and 96
runner seconds. Reclassifying their combined 183 seconds changes attribution,
not the complete 3,369-second total or the historical failure. A native-observation
fixture repeats job identities across attempts, includes successful and failed
work, and verifies one charge per physical job and profile-preserving aggregation.
Earlier reports retain their original labels; regenerate a named later cohort
with the new collector rather than rewriting frozen measurements.

## Further work

Main-push image selection combines the source diff with public-channel identity
reconciliation and unpublished release preparation. A documentation-only source
diff does not establish that image publication is caught up. A blanket skip would
weaken interrupted-publication recovery. The controller already checks live
publication before claiming and dispatching recovery, avoiding a competing
publisher while the scheduled qualification is running.

Keep the active run intact and collect its phase receipts. Compare actual
predecessor reasons and first production initializer stages before implementing
runtime or guest reuse. Preserve the remaining gates in the
[release ledger](v0.8.3-release-plan.md).
