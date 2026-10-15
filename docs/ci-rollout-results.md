# October 14 CI rollout results

The implementation merged through the protected queue in
[PR 162](https://github.com/closure-labs/finite/pull/162) and
[PR 163](https://github.com/closure-labs/finite/pull/163). PR 163 fixed cache
checkpoint contention, selected measured cache defaults, and corrected serial
prompt parsing after kernel output interrupted the LUKS prompt. Its
[PR checks](https://github.com/closure-labs/finite/actions/runs/38638345321)
and [merge-group checks](https://github.com/closure-labs/finite/actions/runs/38639157065)
passed. A test mock also needed an absolute Bash interpreter for the Nix sandbox;
production VM code did not depend on that mock.

Heavy verification ran on GitHub after local Nix evaluation exhausted workstation
memory. Local follow-up used small edits, focused tests and bounded receipts.
No large ISO was downloaded or hashed locally.

## Measured cache decision

The [merged-main benchmark](https://github.com/closure-labs/finite/actions/runs/38639869205)
passed all 27 measurements and aggregation at `b49462573e03`. Each cell below is
the median of three complete jobs, including diagnostics and post-job handling,
and excluding queue wait.

| Tool | Store snapshot | Sources | No Actions cache |
| --- | ---: | ---: | ---: |
| Image tools | 133 s | 38 s | 37 s |
| Scanner tools | 127 s | 44 s | 40 s |
| Repository audit | 128 s | 36 s | 38 s |

All nine baseline jobs restored the same 1.82 GB snapshot. All nine source jobs
hit the same exact 75.1 MB source key. Source, lock, Nix version, output paths and
closures matched across lanes. Runner-image versions varied, limiting causal
claims. Source-cache benefit was inconsistent across the completed experiments.
Automatic small jobs now skip Actions caches while retaining public substituters;
aggregate checks retain bounded source-sensitive store snapshots. Explicit
`cache-mode: optimized` remains available for source-cache experiments.

## Production qualification and original ISO reuse

The initial rollout failed overall because generic rollback never recognized a
split disk-unlock prompt. Its preserved next ISO was correctly ineligible for
reuse. The parser fix changed qualification inputs, requiring a new seed.

The [corrected seed run](https://github.com/closure-labs/finite/actions/runs/38639819537)
passed all four build/security/signing gates, all eight VM phases, all four
aggregates and promotions, and the final CI gate. Authenticated receipts verify
Secure Boot, encrypted root, both desktop manifests, source/tool/firmware bindings,
and rollback checksums. Overall elapsed time was 67.43 minutes; summed job time
was 327.42 minutes. These timestamps are observations, not billed usage or a
controlled comparison with the earlier implementation.

The normal one-channel [successor run](https://github.com/closure-labs/finite/actions/runs/38648164385)
built a distinct next digest at the same revision and named the seed as its
predecessor. Fresh security, signing, both VM phases, aggregation and promotion
passed. The hosted upgrade job downloaded and authenticated the seed's preserved
archive, verified its original ISO and installation hashes, and completed
install, upgrade, rollback and desktop checks. Whole-qualification reuse remained
disabled.

| Next qualification measurement | Seed | Successor |
| --- | ---: | ---: |
| Predecessor ISO preparation | 790.27 s: lookup miss plus regeneration | 128.18 s: restore and verification |
| Complete upgrade job | 32.28 min | 19.33 min |
| Qualification elapsed | 34.27 min | 31.80 min |

The restore received approximately 5.65 GB of runner traffic, including the
5.63 GB archive. Its archive digest was
`a9837bbb4490cd0394ef0ed7347cb082e752ea56f9b5397a21e37832fb498e3e`;
its original ISO digest was
`16e7bc6676f795803839f5db395a9728be896b0fbd96133f3008e49f1a3c8e25`.
The observed preparation reduction was about 11 minutes. Fresh install remained
the critical path, so qualification elapsed fell by about 2.47 minutes. Different
candidates, execution times and runners prevent attributing all phase differences
to caching. Available stage JSONL survives artifact aggregation; ISO-generation
duration remains in job logs and VM-stage durations in their existing JSON files.

At completion of this pilot, preservation and predecessor reuse were restricted
to `finite-next`, with seven-day artifacts and two successful generations per
selected profile.
Failed-origin and diagnostic receipts cannot become trusted producers.

## Cachix validation and operating decision

The writer was enabled only after successor overall success. A metadata-only
check verified all five channel tags, pinned bases, current build identities,
generic/latest alias equality, unchanged main and absence of active publication.
The [reconciliation trigger](https://github.com/closure-labs/finite/actions/runs/38654233864)
then confirmed `profiles=[]` and passed without image builds or qualification.

The [isolated writer](https://github.com/closure-labs/finite/actions/runs/38654727139)
verified its checkout SHA, realized proofs and tools without credentials, then
used the SecretSpec `cache-writer` scope only for the final upload. Its authenticated
manifest contains 12 proof roots, at most 112 bytes each, and four allowlisted tool
closures, each below 2 GiB. Preparation took 199 seconds, push six seconds, and
the whole writer job 241 seconds. Cachix reported 20 uploaded paths and 132 already
present. Overlapping closure sizes do not establish transfer totals.

The [post-writer benchmark](https://github.com/closure-labs/finite/actions/runs/38655239067)
passed all 27 measurements and aggregation. All nine no-Actions readers copied
their exact tool root and resolver root from `finite-os.cachix.org`. The manifest,
source, lock, Nix version, platform, output paths, closure sizes and pre-writer /
writer / post-writer chronology matched.

| Complete no-Actions job median | Before writer | After writer |
| --- | ---: | ---: |
| Image tools | 37 s | 34 s |
| Scanner tools | 40 s | 35 s |
| Repository audit | 38 s | 36 s |

Runner-image sets differed for all three tools. These are observed reductions
with proven substitutions, not controlled causal savings. Applying the medians
to nine readers gives roughly 30 seconds of apparent savings against 241 seconds
of seeding. Positive net runner-time benefit remains unproven, including any
check-proof benefit. Automatic writing is therefore disabled after the completed
pilot. Public reads remain enabled and can use the published paths.

## Final switches and next plan

These values record the initial pilot's completion. The later
[v0.8 continuation](v0.8-release-plan.md) expands preservation to all four
channels and tracks implementation of the priorities below.

| Public repository variable | Final value |
| --- | --- |
| `FINITE_OPTIMIZED_CACHES` | `true` |
| `FINITE_QUALIFIED_ISO_CHANNELS` | `finite-next` |
| `FINITE_QUALIFIED_ISO_PRESERVATION` | `true` |
| `FINITE_CACHIX_WRITER` | `false` |
| `FINITE_REUSE_INVENTORY` | Unset: disabled |
| `FINITE_GRYPE_DB_CACHE` | Unset: disabled |
| `FINITE_QUALIFICATION_REUSE` | Unset: disabled |

The next work should follow the measured bottlenecks:

1. Benchmark verification of the exact local OCI build against registry pull
   verification. The measured warm image build stages took 12-19 seconds;
   immutable verification pulls took 184-278 seconds. Retain exact published
   digest, platform, signature and runtime checks, and compare at least five
   equivalent warm runs plus a cold run before changing publication behavior.
2. Make writer preparation selective and measure amortization before reenabling
   continuous writes. Record cold and warm writer costs, actual reader frequency,
   check-proof substitutions and complete job time at matching source/tool
   identities. Batch repeated evaluations where their output association and
   allowlist can remain independently verified. Reader hits alone do not prove
   positive net benefit.
3. Separate shipped image inputs from host qualification inputs. Currently a
   host parser change also changes image identity. Require tests proving host-only
   changes invalidate qualification and ISO context while payload/kernel changes
   still rebuild every affected image; preserve fresh security and promotion gates.
   Introduce this contract change alongside a planned update to avoid an extra
   qualification generation solely for the migration.
4. Run independent inventory and Grype transport pilots on unchanged image
   digests. Compare complete audit time with mandatory database refresh, policy
   reevaluation, signatures and native-content hashes. Exact qualification reuse
   needs its own justified same-candidate/same-predecessor case and age checks
   at promotion. Keep these switches off until their correctness and net benefit
   are measured.

See [CI rollout](ci-rollout.md) for scoped tasks and rollback commands, and
[CI and releases](ci-and-releases.md#secretspec-and-local-tasks) for GitHub-backed
SecretSpec scopes and local devenv tasks using pass.
