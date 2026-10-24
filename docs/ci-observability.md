# CI stage and cohort observations

The observation endpoint remains `2026-10-30T05:01:17Z`. Keep the original
rollout anchor `2026-10-23T05:01:17Z`; later producer revisions are separate
cohorts and must not be attributed to the first VM tools rollout. Natural runs
supply evidence. This change does not dispatch extra VM rounds.

`vm-acceptance.sh` retains the historical combined `home-activation` interval.
Its nested guest stages now separate startup checks, Homebrew setup, predecessor
preparation and `home-init`; a separate host stage records persistence and
customization fixtures. Initialization still runs once, with inherited
`NIX_CONFIG` and its original stdin isolation. The guest EXIT trap records the
active failed stage; unstarted stages are absent rather than zero. SSH loss can
leave incomplete guest evidence. Host installation failures and cleanup have
status-bearing timings. Complete acceptance occupancy includes cleanup and log
export, so nested measurements must not be added to their parent intervals.

Main qualification records `image-acquisition` (immutable source tag copy),
`installer-prepare`, `iso-build` and `vm-acceptance`. ISO construction includes
installer-internal image transfer; it does not isolate that transfer from Lorax
work. Failure statuses propagate unchanged. No installer or guest behavior is
changed, and unseeded fresh installs and actual bootc activation remain required.

Qualification phases probe usable KVM before Nix setup, image acquisition and ISO
construction. The bounded probe checks Linux KVM API version 12, creates an empty
VM descriptor and closes it without allocating guest memory or booting a guest.
Missing devices, denied access and VM creation failures stop the phase and retain
their distinct failure stages in `*-vm-host.json`, uploaded even on failure. A
timeout may leave no probe receipt; the native step still records failure. The
later VM launch retains its own KVM requirement.

Host receipts record kernel, CPU model, runner image and effective CPU/memory
capacity using the same cgroup-aware detector as Nix setup. Missing capacity is
explicitly unknown and does not create a new eligibility threshold. The expected
guest remains QEMU q35 with SMM, KVM, two vCPUs and 4 GiB RAM. These observations
do not establish resource contention, a speedup or complete guest bootability.
See the [Linux KVM API](https://docs.kernel.org/virt/kvm/api.html) for the empty-VM
probe's limits. Use natural qualification runs to observe rollout costs; this
change dispatches no additional full VM rounds.

The read-only collector joins native image and qualification-phase archives,
limited to 16 archives of 8 MiB each per run and 40 archives per collection.
Security phase receipts can prove inventory reuse; a fresh inventory alone
does not prove eligibility or a miss. It verifies native run/source and
archive digests, bounds expansion and reads only stage receipts. Expired,
oversized, unmatched and missing receipts retain explicit coverage gaps.
Candidate and tool identities are observations, not authorization. Native job
IDs remain unique across attempts; duplicated receipts are deduplicated without
charging their nested durations as additional runner occupancy.

Reports group workflow, event, profile, role and exact producer revision. They
rank recurring work by runner occupancy with job frequency, medians, sole-runner
occupancy and observed final-job counts. Sole-runner intervals provide a measured
lower bound on workflow blocking time; partial or anomalous timing remains unknown. Final-job counts describe the workflow tail; they do not
reconstruct the dependency DAG. Exact critical-path contribution remains unknown
until dependency evidence is available. Reuse eligibility, hits and miss reasons
are distinct: a missing receipt is unknown, and unavailable does not prove a
context mismatch. Compare complete cohorts before changing installer runtime
reuse or guest closure transport. Changing VM helpers invalidates their authenticated reuse context on first rollout;
keep that reconstruction cohort separate. No savings or benchmark adoption is claimed.

Run the collector with `--receipts --rollout 2026-10-23T05:01:17Z` after the endpoint to finish the assessment. Include failed,
cancelled, active and cleanup work and identify incomplete later cohorts.
Automatic Cachix writing and Grype database transport remain disabled.
