# Installer benchmark controls and CI savings

The first corrected zstd and default controls passed both profiles' fresh-install
and upgrade/rollback qualification. Their native aggregates and hash-bound
desktop acceptance also passed. The [cold observation](ci-installer-cold-observation-2026-10-24.json.gz)
preserves those results separately from the earlier incomplete and failed
snapshots in the [diagnostic report](ci-iso-compression-diagnostic.md).

| Profile | Default workflow runner seconds | Zstd workflow runner seconds | Observed reduction | Default fresh ISO bytes | Zstd fresh ISO bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| finite | 3357 | 2956 | 11.95% | 5154144256 | 5218238464 |
| finite-dev | 3777 | 3145 | 16.73% | 7127236608 | 7191396352 |

These are descriptive comparisons. Three of four profile/phase pairs used
different runner image revisions; runtime RPM/repository cohorts were unknown.
Pinned VM tools, firmware, immutable products and base qualification contexts
matched. The observations cannot pass the performance gate. All diagnostic
workflow cost, including 328 seconds from the earlier failed probe, totals
13563 runner seconds. Source-check cost is separate. Nested ISO stages are not
additional runner cost. Actual registry storage and deletion cost is unknown.

## Bound provenance before repeating VM trials

Diagnostic installer containers observe the pinned Lorax
[runtime builder](https://github.com/weldr/lorax/blob/lorax-44.6-1/src/pylorax/treebuilder.py)
after package installation and immediately before squashfs creation. Each
original method still runs once with its original arguments. Hashes bind the
resolved RPM set before cleanup, package header digests, installer RPM set,
repository configuration and downloaded `repomd.xml` files. Effective compression
arguments are observed separately; the cohort hash excludes the compression
choice so both arms can match. Repository absence remains unknown.

Inventory output, directory traversal, metadata reads and marker records are
bounded. The host streams logs and retains a small runtime receipt, including
partial evidence on failed construction. A successful diagnostic ISO without a
valid unique receipt fails. A declared runtime mismatch or missing repository
metadata stops before VM work. Only diagnostic containers install this observer;
the production Containerfile and compression remain unchanged.

The manual `installer-smoke` mode builds each diagnostic installer variant and
checks the actual pinned Lorax, DNF and RPM APIs on a 512 MiB container, without
ISO construction, image products or VMs. Its repository fixtures are explicitly
not runtime cohort evidence. Use it before spending full qualification rounds.

## Predeclare native samples

`scripts/ci/installer-benchmark.py plan` freezes a source head, runner image,
authenticated immutable product inputs and observed fresh/upgrade runtime
cohorts for each profile. Supply `--products` with the authenticated pilot request
and `--cohorts` with a profile-to-phase hash mapping. For example:

```sh
python3 scripts/ci/installer-benchmark.py plan \
  --head "$diagnostic_head" --runner-image "$runner_image" \
  --products authenticated-products.json --cohorts runtime-cohorts.json \
  --output installer-plan.json
```

The plan contains one cold and five warm pairs per profile. Freeze it before any
sample dispatch; do not edit it afterward. The existing manual workflow accepts
an optional `installer_benchmark` JSON input containing exactly:

```json
{
  "schema": 1,
  "planSha256": "CANONICAL_PLAN_SHA256",
  "pair": "warm-1",
  "temperature": "warm",
  "runnerImage": "20261023.334.3",
  "runtimeCohorts": {"fresh": "OBSERVED_SHA256", "upgrade": "OBSERVED_SHA256"}
}
```

The uppercase values above are placeholders. The canonical plan hash is SHA-256
of sorted-key, compact JSON, as produced by the reporter's `sha` function.
Pair IDs are `cold-1` and `warm-1` through `warm-5`; each has a `default` and
`zstd` workflow with both VM phases. Each phase checks the declared runner image
before Nix setup, disk cleanup or image transfer.

Cold phases restore no Actions cache. Warm phases request the existing bounded
Nix checks snapshot without saving a branch cache. A warm sample requires an
observed exact cache hit and the same restored key in both arms. Empty, missing
or false hit observations do not qualify. This measures warmth of the host tool
snapshot; Lorax DNF inputs remain fresh and guests remain unseeded. Restore,
setup, retention, post-job work and cleanup all remain charged in native job
cost. No full VM warm-up rounds or guest closure seeds are added.

After collection, supply **all** native workflow IDs from the frozen source
since plan creation, including failures, in a JSON list:

```sh
python3 scripts/ci/installer-benchmark.py report \
  --plan installer-plan.json --runs installer-runs.json \
  --output installer-comparison.json
```

The read-only reporter authenticates native workflow/run/source and artifact
digests, bounds ZIP expansion, checks controls against the frozen plan and
verifies product/ISO/context/desktop bindings. It uses unique native job costs
across attempts, retains unknown durations and failures, and rejects a run list
that omits native work. Failed, retried, mismatched or partial work cannot be
replaced selectively. Both profiles need five matched warm pairs, with each complete native phase-job and total
workflow warm median improving by at least 10 percent and 30 seconds; each cold
phase and the cold workflow must regress no more than 10 percent. Size effects
remain explicit. A report never authorizes publication or enables compression.

No repeated matrix is dispatched automatically. First establish actual runtime
cohorts at the reviewed head and inspect measurement cost. Preserve both
profiles' actual Secure Boot, encrypted-root, SELinux, Nix sockets, Home Manager
activation and persistence/customization acceptance throughout.

## Additional savings in this change

* Diagnostic prepare and aggregate jobs use standard-library Python and skip
  Nix installation. The four observed workflows spent 44–51 seconds each in
  these two Nix setup/post-job steps. This identifies removed work; net savings
  need a later native observation. Production eligibility checks keep Nix.
* Explicitly classify reviewed compression/provenance helpers and the existing
  image-tools diagnostic/report paths as host-only inputs. Future edits keep
  full source checks while avoiding unrelated OS payload rebuilds. Installer
  and VM helpers still invalidate their qualification context. The identity
  policy update itself can cause a one-time reconstruction; do not relabel old
  candidates or claim its rollout as a steady-state saving.
* Diagnostic aggregate evidence retains 14 days instead of 90; production
  qualification keeps 90 days and phase evidence keeps seven days. Existing
  retained artifacts are untouched. Configured logical retention falls by
  76 days per future diagnostic aggregate; actual billed savings are unknown.
* Cohort rejection and the inexpensive pinned-installer smoke move invalid
  experiments ahead of full VM work. No replacement runs chase a faster result.

The earlier transport benchmark failed adoption; retain original-ZIP product
verification. Automatic Cachix writing and Grype database transport remain off.
Installer-runtime reuse and guest closure transport remain proposals; current
measurements do not establish avoidable work for them. The seven-day assessment
remains incomplete until **October 30, 2026 at 05:01:17 UTC**, with later rollout
cohorts reported separately.
