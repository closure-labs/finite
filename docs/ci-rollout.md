# Measured CI rollout

> Historical record: October 14 CI rollout plan. For current operations, use
> [CI and releases](ci-and-releases.md) and [security review](security-review.md).
> See [reports](reports.md) for dated evidence and related work.

The review branch has passed the 27-run cache experiment and all four diagnostic
Secure Boot qualifications. These receipts validate the installer and test code;
they cannot authorize production promotion or populate production reuse. The
protected pull request and merge queue must also pass `CI gate` at their own
revisions. The initial implementation, hosted fixes and measurements are recorded
in [CI optimization review](ci-optimization-review.md).

The October 14 protected-main rollout, corrected four-channel qualification,
distinct-successor ISO roundtrip and scoped Cachix writer/reader pilot are now
complete. [Measured results and the next plan](ci-rollout-results.md) record the
receipts and final switches. Automatic small jobs skip Actions caches; next-only
ISO preservation remains enabled. The automatic writer is disabled after its
successful pilot because positive net runner-time savings remain unproven.
The procedures below describe how to run another controlled stage.

The [v0.8 continuation](v0.8-release-plan.md) expands original-ISO preservation
to all four channels for its genuine release build and defaults writer preparation
to the four declared tools. Earlier next-only procedures below describe the
completed initial pilot.

## Initial main rollout

After ship approval, use the merge queue. Configure only the measured small-job
cache lane and the one-channel ISO pilot before the main workflow starts:

```bash
gh variable set FINITE_OPTIMIZED_CACHES --repo closure-labs/finite --body true
gh variable set FINITE_QUALIFIED_ISO_CHANNELS --repo closure-labs/finite --body finite-next
gh variable set FINITE_QUALIFIED_ISO_PRESERVATION --repo closure-labs/finite --body true
```

The variables are public bootstrap inputs to the declared SecretSpec `ci-options`
profile. Runtime exports validate boolean values and normalize the channel
selection. Signing and upload credentials remain separate SecretSpec scopes.
Keep `FINITE_CACHIX_WRITER`, `FINITE_REUSE_INVENTORY`, `FINITE_GRYPE_DB_CACHE` and
`FINITE_QUALIFICATION_REUSE` false or unset during this first stage.

Main may publish all changed profiles through its existing security, signing and
boot gates. Only `finite-next` preserves pristine candidate ISOs, attempts
predecessor ISO reuse, prunes its qualified ISO archives and requires preserved
bytes for the exact release path. Other channels retain their explicit standalone
ISO release path. Aggregate Nix checks retain their store snapshot; qualification
jobs keep `cache-mode: none`. Cache housekeeping retains bounded main snapshots
even when experimental flags are off.

The completed warmed experiments selected no Actions restore for automatic small
jobs: source snapshots added overhead or tied without reducing resolver time.
The pilot flag keeps aggregate checks snapshots and public binary-cache reads.
Explicit `cache-mode: optimized` still enables measured source experiments.

Record the merged source SHA, originating build run and attempt, candidate and
predecessor digests, source identity, security verdict, both VM receipts and
successful aggregate. Do not substitute the earlier branch diagnostic receipts.
The older `c046edd3` candidates generally have incompatible current input
identities; let the planned main build produce and qualify the new candidate A.
Confirm `finite-qualified-iso-bluefin-next-RUN-ATTEMPT` exists with its original
ISO, `SHA256SUMS`, installation metadata and signature evidence.

The initial main run, [38626712683](https://github.com/closure-labs/finite/actions/runs/38626712683),
passed all four security/signing gates and seven of eight VM phases. Generic
rollback stopped at disk unlock because a kernel record split the word
`passphrase` in its serial prompt. Generic promotion was blocked; `finite-next`
and both developer channels passed their aggregates and were promoted. The
originating run failed overall, so even its preserved `finite-next` ISO is not a
trusted reuse producer. Do not relax that successful-origin requirement.

The follow-up recognizes complete interleaved kernel records without changing
raw logs, key redaction or one-time submission. It also retains separate fresh
and upgrade stage timings and measures predecessor ISO retrieval. These changes
alter the qualification context: seed a new candidate A under the fixed harness,
require its originating run to succeed, then build distinct B. The hosted B job
must verify and extract the large preserved archive; do not fetch it locally.

## Warmed source cache measurement

This source lane remains an explicit experiment. Prefer an existing
`nix-sources-v1-Linux-X64-LOCK` cache from a trusted main job that explicitly
selected `cache-mode: optimized`. The initial rollout's main selection job seeded
the current lock before the default was refined. Automatic small jobs now skip
Actions restoration and saving. If a future lock has no source snapshot, one
initial main benchmark can seed it through its optimized jobs; count misses as
seeding, then measure after the exact current-lock snapshot exists.
Confirm that cache using the Actions listing, then run at a fixed main revision:

```bash
gh cache list --repo closure-labs/finite --ref refs/heads/main --limit 100
gh workflow run benchmark-ci-cache.yml --repo closure-labs/finite --ref main
```

Require all 27 jobs and the aggregate to pass. All nine optimized measurements
must restore the source cache; compare matching source, locks, Nix version and
tool closures. Record runner-image versions, setup plus cold realization, warm
realization, transfer bytes and complete job time, including source-cache save
overhead. Restore source downloads before realizing the SecretSpec resolver, so
hits can also benefit its initial evaluation/download work. The shared setup
validates public bootstrap inputs first and performs canonical SecretSpec export
after restoration; credentials remain scoped to later commands. The SQLite CLI
has a verified 15-second lock wait for both restoration and post-job snapshots;
permanent schema locks still fail. Keep the
source lane only when complete job benefit exceeds restore/save overhead. The
completed three-repetition experiment selected no Actions cache for small jobs.

## Predecessor ISO reuse on finite-next

Use the next legitimate candidate B, with B different from A and its publication
record naming A as the predecessor. Prefer an already planned update/build. A
manual one-channel build is available when it is needed for this pilot:

```bash
gh workflow run build.yml --repo closure-labs/finite --ref main \
  -f target=finite-next -f qualify=true
```

This main dispatch runs the existing publication gates and can promote the new
candidate. Keep whole-qualification reuse off so both phases run. Require the
upgrade log to report authenticated predecessor ISO reuse, rather than ISO
generation. Verify the archive SHA, original ISO and installation hashes,
installation tag digest, current installer/test generation and firmware/tools.
Require fresh install, upgrade, rollback, desktop checks and aggregation to pass.
Compare avoided ISO generation against download, extraction and upload time.
Retain only two successful seven-day ISO generations for the selected profile.

An authenticated current-input, unpublished main candidate can sometimes seed A
through `resume_run` and `resume_digest` without another image build. Confirm its
current identity first. Requalifying A after A was promoted changes the current
predecessor to A; that does not demonstrate an A-to-B upgrade. Missing pristine
bytes cannot be reconstructed by regenerating an ISO with another installation
tag. Selected-channel releases fail closed if exact preserved evidence is absent.

## Separate Cachix writer pilot

Enable the writer after the source/ISO stages pass, using the existing token:

```bash
gh variable set FINITE_CACHIX_WRITER --repo closure-labs/finite --body true
```

Publishing requires a successful trusted main `Build Finite` workflow-run event.
A manual cache-maintenance dispatch does not publish. Use the next already planned
successful build. A `reconcile=true` Build Finite dispatch is suitable only when
read-only reconciliation confirms no pending image profiles; otherwise it also
builds and publishes the pending profiles. A failed overall originating build
does not trigger this writer, even when its Nix checks passed.

Require the independent checkout/source SHA check, strict evaluated tool/output
associations, allowlisted roots and two-GiB tool bounds. Optional
`--include-proofs` seeding also validates one-MiB proof bounds. Keys
are resolved only for the final SecretSpec `cache-writer` command, after secret-free
realization. Exclude image stores, VM disks, personalized ISO media and keys.
On three subsequent matched reader runs, require actual substitutions from
`https://finite-os.cachix.org` and end-to-end measurements. Cache configuration
or a successful metadata query alone does not prove reader savings.

## Rollback and later stages

Disable a pilot independently for subsequent runs:

```bash
gh variable set FINITE_OPTIMIZED_CACHES --repo closure-labs/finite --body false
gh variable set FINITE_QUALIFIED_ISO_PRESERVATION --repo closure-labs/finite --body false
gh variable set FINITE_CACHIX_WRITER --repo closure-labs/finite --body false
```

Workflow environment values are snapshots, so existing jobs continue with their
original settings. Disabling preservation stops new uploads, predecessor reuse
and ISO pruning, and restores the explicit standalone ISO fallback when preserved
evidence is missing. Already valid preserved artifacts remain preferred. Turning
off the writer stops future pushes while configured public substituter reads
remain. Turning off optimized caches restores the bounded full-store baseline.

Keep the pinned certificate, earlier eligibility checks and mandatory parallel
qualification gates. Broader ISO selection, exact qualification reuse, inventory
reuse and Grype transport caching each need separate measured main evidence.
Security audits continue to refresh their database and policy even when immutable
inventory is reused.
