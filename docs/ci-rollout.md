# Measured CI rollout

The review branch has passed the 27-run cache experiment and all four diagnostic
Secure Boot qualifications. These receipts validate the installer and test code;
they cannot authorize production promotion or populate production reuse. The
protected pull request and merge queue must also pass `CI gate` at their own
revisions. The initial implementation, hosted fixes and measurements are recorded
in [CI optimization review](ci-optimization-review.md).

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

Record the merged source SHA, originating build run and attempt, candidate and
predecessor digests, source identity, security verdict, both VM receipts and
successful aggregate. Do not substitute the earlier branch diagnostic receipts.
The older `c046edd3` candidates generally have incompatible current input
identities; let the planned main build produce and qualify the new candidate A.
Confirm `finite-qualified-iso-bluefin-next-RUN-ATTEMPT` exists with its original
ISO, `SHA256SUMS`, installation metadata and signature evidence.

## Warmed source cache measurement

Wait for a successful main source-lane job to save a
`nix-sources-v1-Linux-X64-LOCK` cache. An existing main job is preferred. If needed,
one repository security audit can seed the source lane without building images:

```bash
gh workflow run repository-security.yml --repo closure-labs/finite --ref main
```

That audit is read-only and still needs its configured audit App credentials.
Confirm the exact current-lock main cache using the Actions cache listing, then
run the benchmark at a fixed main revision:

```bash
gh cache list --repo closure-labs/finite --ref refs/heads/main --limit 100
gh workflow run benchmark-ci-cache.yml --repo closure-labs/finite --ref main
```

Require all 27 jobs and the aggregate to pass. All nine optimized measurements
must restore the source cache; compare matching source, locks, Nix version and
tool closures. Record runner-image versions, setup plus cold realization, warm
realization, transfer bytes and complete job time, including source-cache save
overhead. The resolver currently realizes before the Actions restore, so source
cache hits cannot eliminate its initial evaluation/download cost. Keep the
source lane only when complete job benefit exceeds restore/save overhead; the
no-Actions-cache lane is also a valid small-job result.

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

Require the independent checkout/source SHA check, successful aggregate proofs,
allowlisted roots, one-MiB proof/two-GiB tool bounds and a successful push. Keys
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
