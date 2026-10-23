# Payload evaluation incident, October 23, 2026

PR #235 merged as `ecf670fa9b91b4b68cef6c1c0e5008d6fa42093d`
after [both queue VM validations passed](https://github.com/closure-labs/finite/actions/runs/39972455258).
Both native-digest-verified queue archives report accepted Secure Boot and
encrypted-root validation for their respective active profiles.

Its [first main execution](https://github.com/closure-labs/finite/actions/runs/39980522095)
then exposed a pre-build evaluation failure. The
[standard build job](https://github.com/closure-labs/finite/actions/runs/39980522095/job/120509623632)
failed in `Prepare candidate publication`: `nix eval .#image-payload.drvPath`
exceeded its 300-second deadline. It had not constructed a new image or supplied
signing keys. The developer build completed that evaluation and subsequently
staged the payload through another root-flake operation. These observations
identify the failed boundary; they do not establish whether network fetching,
output composition or another resource stall consumed the standard job's time.

The health query also excluded all active runs. It therefore could not report
this standard-profile failure while the developer profile was still qualifying.
Health now includes a read-only `activeBuilds` summary with failed step names,
running phases and approval/environment waits. Historical qualifications and
promotions still come only from completed runs. A failed active profile marks
pipeline health unhealthy while leaving the prior successful channel records
visible. Queued and normally running builds do not imply a delivery failure;
approval waits remain informational blockers. This adds no dispatch, signing,
publication or cache-write operation.

The standalone `lib/ci-payload.nix` entry now imports the existing payload
function with the root flake's actual inputs, shared package import, Foundation
catalog projection and consumer scaffold. It avoids composing Finite's Den
outputs while preserving the root lock graph and Foundation follows. It does
not substitute a different Foundation or devenv version. Image identity and
staging use this same entry; the public flake output remains available.

An initial attempt to read `.inputs` directly still evaluated the root outputs.
A deliberate failure in the module evaluator exposed that flaw. The root flake
now defers all nine existing public exports, so reading its input graph does not
compose Den. Accessing any public export still evaluates the original module
result and rejects an unexpected new export instead of silently dropping it.
The `flake-input-boundary` proof covers deferred evaluation, normal exports and
rejection of an unlisted future export.

The mandatory aggregate adds a `payload-entry` proof comparing exact derivation
paths with the public output. Any divergence rejects CI. Existing profile,
content, mode and payload identity hashing remains in place, including hashing
the changed controller scripts themselves. Nix evaluation, authorization,
integrity and build errors remain terminal; the deadline was not increased and
no outer evaluation retry was added. Local-path evaluation needs `--impure` to
open the checkout, with lock updates and lock writes explicitly disabled.

With Den composition deliberately replaced by a failure, two local warm
observations succeeded in 0.583 and 0.345 seconds. Both returned
`/nix/store/ydq3wbhv6vns4440rf1bzy4pdc1kznmv-finite-image-payload-0.8.3-dev.drv`,
exactly the derivation built by the successful developer job at 15:50:07 UTC.
Local Nix was Determinate 3.23.3 / upstream 2.35.3; hosted Nix was Determinate
3.23.2 / upstream 2.35.3. These are local observations from one checkout, not a
controlled cold benchmark, a hosted savings estimate or complete-job medians.
The [companion JSON](ci-payload-evaluation-2026-10-23.json) records their scope.

Focused validation passed 79 image identity, selection, toolchain, candidate
resume and build-boundary tests, plus the pure Nix boundary fixture. The new identity tests preserve the explicit
derivation contract and verify that evaluation failures stay terminal. Hosted
aggregate verification, including exact derivation equality, is required before
readiness. Full image/VM acceptance remains required by the merge queue and
publication workflows; this change does not reuse an earlier candidate verdict.

Rollback: revert the standalone entry, lazy export boundary and two callers together, restoring
the original public `image-payload` evaluation and staging commands. Keep the
original failed run and developer candidate evidence. Do not redispatch or
replace a recorded candidate as part of this fix. The frozen 0.8.2-dev execution
and existing published assets remain untouched. Automatic Cachix writes, Grype
DB transport and the unmeasured retained OCI export alternative remain disabled.
