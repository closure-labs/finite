# Predecessor ISO reuse audit, October 23, 2026

The predecessor artifact lookup unnecessarily rebuilt an installer after a
change to `scripts/bluebuild/local-vm.sh`. That entry point runs only for PR and
merge-group validation and never produces a published pristine candidate ISO.
The complete qualification context deliberately includes it; using that complete
context for pristine artifact lookup made the lookup too restrictive.

The authenticated qualification archives from
[main 1060](https://github.com/closure-labs/finite/actions/runs/39910736417) and
[main 1071](https://github.com/closure-labs/finite/actions/runs/39931669315) show,
for both active profiles, that 1071's predecessor is exactly 1060's candidate.
The only changed context input was `scripts/bluebuild/local-vm.sh`. The standard
profile's [upgrade job](https://github.com/closure-labs/finite/actions/runs/39931669315/job/120363462963)
reported no compatible retained ISO at 10:22:02 UTC and later reported an
835-second ISO generation. This excludes earlier setup and lookup time.

The later [scheduled run](https://github.com/closure-labs/finite/actions/runs/39960735979)
successfully restored an authenticated pristine ISO on both profiles, verified
current signatures, then performed upgrade and rollback acceptance. Its retained
stage reports measured the entire restore command, including artifact lookup,
download, verification and copying:

| Profile | Restore seconds | Origin run |
| --- | ---: | --- |
| finite | 130.710 | 39944152028 |
| finite-dev | 387.376 | 39950048323 |

Each row is one observation on Ubuntu 24.04 runner image `20261012.334.1`, source
`23c06c71c671106ae8ac7ea5112224c5c5d400be`. These are different candidate
cohorts from 1071; they establish a working restore path, not a matched savings
estimate, median, or complete-workflow cost reduction. Native archive bindings
and the exact comparison are in the [companion report](ci-predecessor-2026-10-23.json).

The fix projects only the pristine artifact comparison, excluding `local-vm.sh`
and `reuse-predecessor-iso.py`. The latter reads artifacts only in the upgrade
lane and cannot affect the fresh lane's pristine ISO generation. Every other
input, including unknown new helpers, content, executable modes, certificate,
installer pin and VM checks, remains conservative. A generation-input mismatch
reports its paths when checked directly. The complete qualification receipt and
its original context hash remain intact; old VM verdicts gain no new reuse
eligibility. Producer identity, archive digest, ISO checksum, installer/image
association, immutable tag resolution, current Cosign verification and fresh
upgrade/rollback qualification remain required.

Regression coverage exercises both excluded entry points, unchanged strict
qualification reuse, forged context hashes, unknown inputs, modes and missing
contexts, alongside the existing authenticated restore, missing-tag and terminal
signature failure fixtures. Hosted rollout still needs review before claiming
that the newly eligible cross-context restore has occurred in production.

Rollback: restore the exact input equality in `compatible()` in
`scripts/bluebuild/reuse-predecessor-iso.py`. This returns eligible misses to the
existing full ISO construction fallback without deleting artifacts or changing
publication authority. Keep automatic Cachix writes and Grype DB transport off.

The retained OCI export alternative remains unadopted: these ISO observations do
not satisfy its separate five warm and one cold matched comparisons per profile.
The seven-day workflow observation ends October 30; no cost reduction percentage
is claimed before that report completes.
