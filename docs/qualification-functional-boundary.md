# OS and functional qualification: first phase

Each applicable fresh/upgrade worker still creates or authenticates one pristine
ISO and tests one private guest disk. Homebrew setup, predecessor preparation,
Home Manager activation and actual customization persistence remain required.
No dependency label, path classification or cache hit skips them.

The worker now records functional subprocess exit codes and continues mandatory
OS assertions after functional failure. Download-independent startup includes the
profile, enforcing SELinux, Nix mount/daemon and a persistent Nix state marker.
The existing firmware, enrolled key, Secure Boot, encrypted-root, kernel,
wrong-key rejection, immutable signed update, updated-image identity, reboot,
Nix-state persistence and OS rollback assertions retain their existing order and
profile conditions. The Home Manager customization probe still runs before the
signed update and after its reboot. No Home Manager rollback test is added.

`vm-functional.sh` holds the original initialization and persistence probes.
A separate Bash process preserves `errexit`/`pipefail` while its caller records
failure; an `if` around an inline shell function would silently disable errexit
inside that function. Log-capture failure is a functional failure too.

The workflow's explicit **functional** job requires successful OS phase workers
and validates zero-status initialization receipts for fresh, and initialization
plus post-update receipts for upgrade. It performs the existing single native
artifact collection and qualification aggregation. The native display name
`aggregate` remains unchanged: historical ISO recovery, release readiness and
completion readers authenticate that producer name. This compatibility detail
avoids a new artifact-transfer boundary or duplicate collection job.

Functional receipts are inside the same authenticated phase ZIP as OS acceptance,
context and ISO bindings. Existing exact source/run/attempt/job and archive-digest
verification, carried-attempt age, profile/candidate/predecessor checks, desktop
coverage and publication guards still apply. Missing, failed or malformed
functional receipts block final acceptance even with passing OS evidence. A
functional failure can make its OS worker green, but cannot make qualification,
the calling workflow or publication green. Old contexts cannot be reused after
the changed source/workflow hash; no old receipt is relabeled as functional proof.
Standalone and experimental VM callers retain the combined nonzero exit contract
unless qualification explicitly enables deferred functional verdicts.

## Evidence and validation plan

The motivating current-main run 41338952900 lost a booted fresh guest to a
cache.nixos.org HTTP 416 during Home Manager realization. The successful upgrade
reported 354 seconds initialization and 299 seconds Home Manager work, with
1,394 substitutions and 143 builds. These are observations, not a measured
speedup or proof of a cache fault's cause.

Lightweight tests cover failure propagation through the real stream capture,
continued OS work, strict standalone failure, missing/wrong/failed functional
receipts, required upgraded-guest coverage and the unchanged native producer
name. Existing signature/update, actual persisted customization, collector
origin/digest, reuse/freshness and workflow-selection fixtures remain applicable.
No image build or VM runs locally.

Before merging or any later path-skip cutover, budget one hosted validation of
both profiles' fresh/upgrade phases on one exact reviewed source: compare OS
assertions, initialized-home and updated-home evidence, desktop receipts, context,
image/ISO digests and guest timing stages with the prior lifecycle. Inject a
controlled functional failure in a separately authorized hosted diagnostic: OS
update/rollback must finish, functional aggregation must fail, and no promotion
may occur. Test OS failure independently: no functional verdict may override it.
Record runner image/resources, queue time, ISO creation, OS stages, functional
stages and total wall time; this phase adds no VM or duplicate ISO and claims no
runtime reduction. There is no added retry, controller, binary cache or closure
transfer. Dependency-aware functional skips or native closure provisioning need
a separate reviewed contract and measured experiment.
