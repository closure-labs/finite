# Matched local builder benchmark

This draft compares the BlueBuild-generated Containerfile with the standalone
Containerfile imported from PR #321 (`e7ea97af2cd720f3f5ac0e662e12f53ba57fadb8`).
It does not replace the production builder or qualify images for publication.
The imported implementation retains its explicit recipe parity contract and
installed Foundation/RPM provenance checks. Its hosted opt-in and implementation
identity now refer only to this benchmark's branch and workflow.

The fixed source baseline is main `49efd91b3ddaa775469b45d94c2e2424df3fa034`.
Before staging, the runner proves that baseline is an ancestor and that recipes,
sources, lock, image payload and existing build/VM scripts have no diff. Both
methods use that same checkout and staged payload. Foundation is locked at
`7a58c945d464c32ae1a86d07a75cce495076a752`, Bluefin at
`afe335088014cf0c20257c64d81a474ff683c9e6796a633ea8ebadee428d26e9` and
Bluefin DX at `4b7a467b6d5f0cd65075802ad2ec9d4a4bb16fedb8d602b688f3ba64d0ab0779`.
The source manifest retains the complete Foundation narHash, tool digests,
reference input identity and implementation hashes; context manifests bind every
file actually sent to BuildKit. The pinned CLI supplies its embedded BlueBuild
scripts. Its generated runtime CLI tag is replaced by the authenticated digest
from the unchanged source manifest, and final labels mark both outputs ineligible
for production. Recipes and production build functions are not edited.

## Cost and pairing

One workflow invocation runs exactly four jobs: two repetitions each of finite
and finite-dev, at most two simultaneously, each capped at 135 minutes. The
corrected run maximum is nine runner-hours plus a ten-minute contract job, leaving
one hour of the initial ten-hour budget for the first failed diagnostic run.
Failed jobs consume the budget and are not automatically retried. Setup and
ordinary required PR CI are additional. There are sixteen build trials and eight
fresh VM validations. No production keys, registry pushes, promotions, hardware
tests or rollback tests are used.

The full cohort runs only when this internal PR is opened or explicitly
reopened. Later pushes run contracts and ordinary CI without purchasing another
cohort. This prevents an evidence/documentation/bootstrap correction from
silently duplicating the measured workload. Reopening requires a newly approved
run budget. The first corrected cohort at `1343248c9eaaa0406b34046e6a5ddf522b84aecd`
was already launched before this budget latch was added. A subsequent CI-only
bootstrap correction retains the same job-level options and `cache-mode: none`;
it does not change either Containerfile, build command, payload or VM harness.

Within each job both methods use the same physical runner and fixed
Buildx v0.38.1 / digest-pinned BuildKit v0.33.1. Repetition one runs BlueBuild
first; repetition two reverses order. Each method receives an empty private
builder and then a warm repeat with identical input bytes and that same builder.
The first method's builder is removed before the second starts. BuildKit cache
is never imported from or written to a registry or Actions cache. Nix Actions
snapshot restoration is disabled; both methods share the same realized pinned
payload and public substituters. “Cold” describes the private BuildKit state,
not a cold Internet, empty host page cache or empty package/registry CDN.

## Measurements and evidence

Payload staging and BlueBuild generation are recorded once per pair. Both
Containerfiles use the same Buildx flags and platform. Assembly first solves with
`type=cacheonly`; a second identical cached solve exports a Docker archive.
Export therefore includes cached graph evaluation, but excludes daemon load.
`docker load`, the identical offline verify-image runtime gate, installed
Foundation metadata and sorted RPM inventory are recorded separately. Daemon
output layers are removed before each next load. This benchmark isolates the
generated assembly graph; it does not measure BlueBuild CLI orchestration of a
production push, signing or publication pipeline.

Both cold outputs run the unchanged local-vm.sh fresh installer harness with
Secure Boot, encrypted root and first-login acceptance. Its timing file separates
OCI export, installer preparation, ISO construction and VM acceptance. Warm
trials repeat assembly/export/load/runtime checks without another VM. Receipts
bind the immutable local Docker ID, source revision, profile and source-input
identity. Unsigned local boot success is not signed upgrade or deployment parity.

Every stage records wall-clock start, monotonic duration and runner network-byte
delta. Full BuildKit raw JSON records preserve network/registry vertices and
cache hits for both assembly and export; a projection retains vertex timestamps.
Network fetches may overlap assembly. Their vertex durations must not be summed
as an exclusive network total or subtracted blindly from assembly. Queue and
setup time come from GitHub's job/step timestamps. CPU model, effective CPU/RAM,
kernel, runner image/name and initial disk capacity are retained in host.json;
GitHub initialization logs supply region. Compare host/image cohorts before
combining repetitions, and report unmatched hosts explicitly.

Artifacts contain public evidence only, not images or Docker archives. Verify
their GitHub archive SHA256 and workflow/head binding before reading receipts.
Compare inventories and installed metadata before interpreting timing changes.
Floating package repositories, BlueBuild module references, host page caches,
network service load and runner region can still vary; preserve resolved build
graph references. Two repetitions characterize observations, not a population
estimate or a causal production speedup. Earlier production runs with registry
cache hits and recovery attempts are contextual evidence only.

The temporary internal branch trigger must be removed before any eventual main
merge. Keep this PR draft until its evidence and maintenance cost are reviewed.
