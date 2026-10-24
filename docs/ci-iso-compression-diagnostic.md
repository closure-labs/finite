# ISO runtime compression diagnostic, October 24, 2026 UTC

Keep this prototype draft until hosted correctness and matched complete-job
cost gates pass. No compression benchmark has run and no speedup is claimed.
Production retains the pinned installer's existing configuration.

## Measured target and rollout

The [#247 protected queue](https://github.com/closure-labs/finite/actions/runs/40061504970)
passed both profiles using Foundation v0.3.3. Its native receipts and bounded
job-log marker intervals are retained in the
[evidence snapshot](ci-iso-compression-diagnostic-2026-10-24.json.gz).

| Profile | Native build job, seconds | ISO construction, seconds | Runtime-image interval, seconds |
| --- | ---: | ---: | ---: |
| finite | 2348 | 745.977 | 261.924 |
| finite-dev | 2800 | 765.277 | 259.774 |

Runtime-image intervals start at Lorax's `creating the runtime image` marker
and end at `rebuilding initramfs images`. They include intervening work and
possible buffering; they do not prove that the entire interval is avoidable.
Nested intervals must not be added to ISO or native job occupancy. The developer
job had 452 measured sole-runner seconds; exact stage-level DAG contribution
remains unknown. These are natural observations, not matched comparisons.

The [#248 main rollout](https://github.com/closure-labs/finite/actions/runs/40066733156)
has authenticated its first compact scanner artifact, 416 bytes for `finite`.
That job cost 613 runner seconds. Its phase observations include 183.716 seconds
of cataloging, 155.070 of extraction, 91.712 of database update and 42.322 of
image transfer. They remain nested within the job. The developer scan and full
rollout were incomplete in this snapshot; this is not a complete cost comparison.
The earlier [scanner report](ci-security-cost-observation.md) and original
measurements remain unchanged.

## Opt-in diagnostic

The pinned [installer Makefile](https://github.com/JasonN3/build-container-installer/blob/bed71f841c250650a70f1ed8315ba92da1591ba6/Makefile)
uses Lorax. The installed Lorax 44.6-1
[defaults](https://github.com/weldr/lorax/blob/lorax-44.6-1/src/pylorax/__init__.py)
select xz with BCJ enabled. Its public compression configuration allows a
separate zstd trial without changing templates, root layout or boot hooks.

The existing manual **Benchmark image tool setup** workflow accepts
`installer_compression=default|zstd` for `validation=qualification`.
`default` leaves installer construction unchanged. The zstd preset selects
level 15 and disables the xz-specific BCJ filter. The pinned container must
support [`mksquashfs -help-comp zstd`](https://manpages.debian.org/unstable/squashfs-tools/mksquashfs.1.en.html)
before the experiment proceeds.

The zstd path requires the exact hosted Finite checkout, explicit validation-only
mode, a non-main branch, the existing benchmark workflow identity and an exact
predecessor digest. Main, PR events, other workflows, unknown presets and missing
predecessors fail before container work. Production callers use the unchanged
default. Both fresh-install and upgrade/rollback phases run for each selected
profile; force-qualification bypasses qualification reuse.

The installer merges only the reviewed compression settings into its existing
Lorax configuration, preserving unrelated settings. It verifies the installed
values and retains both the preset hash and complete installed configuration
hash in installer metadata. Diagnostic qualification identity also binds the
selected preset. Baseline and zstd contexts differ even at the same checkout.
Diagnostic ISO bindings retain measured byte sizes. Production metadata/context
shapes retain their existing defaults.

Existing validation-only evidence cannot authorize publication, trusted
predecessor ISO preservation, qualification reuse or release assets. The exact
signed candidate and predecessor remain independently verified. Secure Boot,
encrypted root, enforcing SELinux, both Nix sockets, real bootc Home Manager
activation, single initialization and customization preservation remain required.

## Hosted pilot and adoption gates

Wait for #248's normal two-profile main qualification and promotion to finish.
Select the exact resulting signed candidate and predecessor digests, build
identity and candidate source revision separately for `finite` and `finite-dev`.
Use the same diagnostic checkout and immutable inputs for both compression arms.
Do not edit decisions, frozen executions, published channels or release assets.

First require zstd correctness for both profiles' fresh-install and
upgrade/rollback phases. Stop on failure before spending repeated benchmark
rounds. Source regressions and mock container fixtures do not prove real
mksquashfs support, kernel decompression, boot acceptance or performance.

Before adoption, declare a matched sample plan and compare complete native job
cost, including setup, installer preparation, acquisition, ISO construction,
installation, acceptance, retention and cleanup. Require at least 10 percent
and 30 seconds warm median improvement, with no more than 10 percent cold cost
regression. Retain output sizes and transfer/storage effects. Unknown or
mismatched runner images, tools, RPM/repository cohorts and input identities do
not establish a matched improvement. Keep partial/failure cost and unknown
values explicit; do not replace mismatched runs with selected faster samples.
If the current logs cannot establish those cohorts, add bounded provenance before
repeated comparisons. Retain production defaults unless every gate passes.

No local Nix aggregate, image or VM builds are needed. Hosted pinned
`.#ci-checks` verifies executable changes; full hosted qualification remains the
behavior gate. Do not run additional full VM rounds solely to fill a report.

The original observation endpoint remains **October 30, 05:01:17 UTC**.
The seven-day assessment is incomplete; later Foundation and instrumentation
cohorts remain separate. Cachix writing and Grype database transport remain
disabled. Installer-runtime reuse and guest closure transport remain proposals.
