# Bounded delivery-health history

The monitor previously inspected only 30 main builds. Source-only green builds
could displace the last image promotion without indicating a publication failure.
It now reads up to five pages of 30 native Build Finite runs, retaining both
active and completed trusted-main runs. The report records whether available
history was exhausted or the 150-run discovery limit was reached.

Qualification and promotion timestamps come from their successful native jobs,
not the workflow's mutable `updated_at`. The monitor compares completion times
across the bounded inventory: an older-created run can promote more recently on
retry. Creation time is therefore not a safe freshness cutoff. The existing
36-hour freshness threshold remains unchanged, including its exact boundary.

Missing promotion evidence is explicitly unavailable or absent from the observed
history, not proof that publication failed. Actual latest-build failures, active
failed phases, partial channel state, authenticated release-publisher failures,
and informational approval waits retain their independent meanings. Source CI
success still does not establish that a new image or release was published.

Discovery and job/artifact reads have a 120-second admission/result budget.
Individual GETs keep their existing bounded transport timeout and retries; an
in-flight request is not forcibly interrupted, but a result arriving after the
budget cannot produce a healthy snapshot. Missing timestamps, incomplete job or
artifact inventories, duplicated pagination identities, unavailable metadata and
expired observation budgets fail closed. Failed inspection still removes stale
same-job snapshots; audit reporting remains independent. No publication,
approval, preparation-dispatch, signing or reservation policy changes.

Offline regression coverage includes more than 30 source-only builds, both
channels and partial channels, the freshness boundary, older-run retries,
mutable workflow metadata, absent/capped history, missing timestamps, unavailable
pages, duplicate runs, incomplete inventories and deadline crossing. Existing
publisher, snapshot, reconciliation and independent-failure checks remain in the
normal hosted aggregate. No image build, VM or hardware test is needed for these
metadata-only regressions. Hosted exact-head CI remains the adoption check.
