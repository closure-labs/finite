# Optional predecessor ISO transfer budget

Only the optional preserved-predecessor ISO restore opts into progress monitoring.
The normal release-evidence fetch keeps its existing strict transfer behavior.
A miss regenerates the installer for the same signed predecessor and still runs
the genuine upgrade VM test; partial bytes never authorize reuse.

The existing 600-second cap remains. The reader samples archive byte progress at
most every five seconds. After 120 seconds of startup grace, 90 seconds without
new bytes triggers fallback. It also falls back when both the whole-transfer
rate and the recent 60-second rate project more than twice the remaining budget,
continuously for another 60 seconds. Improving transfers and transfers on track
to finish near the cap retain their budget. Progress is only a transport hint;
the full declared size and archive digest are still authenticated before any
extraction, followed by all existing ISO, installation and signature checks.

The failed baseline dev-upgrade transfer received 2.04 of 7.14 GB in 600 seconds
before regenerating its predecessor in another 724 seconds. A deterministic
constant-rate fixture with that ratio falls back at 180 seconds. Fixtures for
131/387-second successful transfers and 590/600-second productive transfers do
not trigger early fallback. This is a policy simulation, not a hosted speedup
measurement. Bursty or recovering transfers may still conservatively regenerate.

HTTP failures, corrupt metadata, wrong digests and signature failures remain
fatal. Only this exact optional transfer's timeout or progress stop is a miss.
The child is killed and reaped before fallback. Diagnostics distinguish
`iso-transfer-unproductive` from `iso-transfer-timeout`, with bounded origin IDs
and byte counts. No partial output is installed at the caller's destination.

Full qualification-input comparison remains conservative. Changing the shared
release reader can invalidate older generation-input snapshots on first rollout;
this PR does not expand the generation-input exclusions to avoid that miss.
Hosted validation is required; no local VM or production promotion was run.
