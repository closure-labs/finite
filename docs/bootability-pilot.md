# Advisory update bootability pilot

This draft runs alongside the existing required VM gate. It does not authorize
promotion, change a ruleset, remove any required test or replace production
qualification. The existing workflow, preflight, signature policy and evidence
consumers are unchanged. The shared VM helper defaults to its existing path;
only the explicit hosted manual pilot workflow can enable its new branch.

## Design and cost boundary

First cohort: **one end-to-end hosted trial for each of `finite` and `finite-dev`,
120 minutes maximum per job, at most two concurrent** (240 runner-minutes maximum
for the two pilot jobs). The internal installer/boot command has a 105-minute
limit; installation retains its 45-minute limit, each boot ten minutes, signed
import thirty minutes. First-attempt enforcement rejects automatic reruns.
Do not redispatch a failed expensive trial without a new budget decision. Check
native runs for the exact head/profile before dispatch. Per-profile concurrency
serializes duplicate dispatches but is not a lifetime budget ledger; the operator
must enforce the one-trial cap. No image or VM workloads run on the XPS.

A separate ten-minute Python/shell contract job runs on relevant PR changes and
manual dispatch, and emits functional selection shadow evidence. Ordinary PR CI
still runs under the existing rules, separately from this pilot budget. New
helpers are conservatively treated by the existing image selector; no image
identity exclusions or old gate selection rules are changed to save pilot cost.
Consequently ordinary PR CI can build images and exercise the old required VM
gate. No saving from replacing that gate is claimed.

For this unmerged draft, dispatch the existing `benchmark-image-tools.yml` on
the draft branch with `validation=bootability-pilot`; it calls the separate pilot
workflow without changing production qualification eligibility. The new workflow
also exposes direct manual `pilot` mode after registration. The manual pilot takes exact signed predecessor/candidate digests, candidate
build identity and source revision. It verifies candidate signature/labels and
copies expected profile/kernel metadata from that exact image without executing
it. It uses the existing pinned ISO producer, installer hook, encrypted Anaconda
layout, UEFI/q35/SMM firmware, Secure Boot and MOK setup. It freshly installs the
predecessor, boots it, runs `bootc switch --enforce-container-sigpolicy` to the
immutable candidate, powers off, then boots the installed disk again. It checks
both a staged deployment and the **booted** candidate. An old-deployment fallback
or merely staging the candidate fails.

The guest probe checks local-fs and multi-user targets (bounded wait), excludes
rescue/emergency targets and current-boot initramfs failure messages, compares
running kernel/profile, resolves `ostree=` to the booted deployment checksum,
checks physical `root=UUID=` and `rd.luks.uuid=` against mounted block devices,
and verifies actual LUKS ancestry for `/sysroot` and `/var`. The host checks the
candidate against the signed index or its Linux/amd64 manifest, a changed boot ID
and OSTree checksum on the same root, Secure Boot enabled and actual enrolled MOK.
The receipt binds firmware code/template/variables hashes. Missing, duplicate,
malformed, incomplete or truthy-string evidence rejects. Native run/head/artifact
origin must additionally be authenticated when interpreting a downloaded receipt;
a standalone JSON status is not trusted provenance.

The pilot does not call wait-nix, initialize HM or Homebrew, establish personal
persistence, perform the wrong-key negative VM test, run desktop/security
functional probes, or perform OS/HM rollback. Normal shipped OS services remain
enabled and untouched. The test-account label prerequisite drops its test-only
Nix ordering in pilot mode; it still labels keys before SSH. Bootability may pass
with unrelated failed functional services only if local-fs/multi-user are reached.
The image's existing bootc lint and initramfs `/init`, matching modules,
ostree/crypt/systemd-cryptsetup/fido2 checks remain additional production checks;
they are never accepted as proof of an actual boot.

## Credentials and fixture investigation

**No installed predecessor fixture is retained in this first pilot.** The current
acceptance disk contains an unlocked sudo test account, authorized key, LUKS
credential and initialized personal state. Neither redaction nor deleting a key
file proves its disk blocks sterile. Do not upload it.

Fresh setup creates one random LUKS key and one passwordless ephemeral SSH keypair
inside a mode-0700 `/tmp/finite-vm.*` directory. The locked, temporary `finite-test`
account has only that run's public key and exists only on that disposable disk.
The LUKS key is masked in live Actions output; installer serial output is not
streamed in pilot mode. No production credential/private signing key is copied
into the guest. Registry authentication remains on the hosted runner; the guest
performs its signed public-image switch under the existing container policy.
Cleanup kills QEMU/unlock processes, removes raw state, keys, kickstart, disk,
firmware variables and private diagnostic snapshots. An `always()` runner step
removes remaining state and logs out registry clients; runner destruction is the
last boundary for hard cancellation. No reusable personal state is retained.

Uploads use exact allowlisted paths: pilot receipt, stage timings, KVM host
receipt, plus a separate selector report. No raw/redacted journals, serial output,
SSH private keys, kickstart, firmware variables, ISO or disk image is uploaded.
Failure may yield timings without a pass receipt; that is an incomplete failed
trial, not a qualified candidate. The pilot never writes `acceptance.json` or
uses a `qualification-*` artifact name.

A later fixture design must use a dedicated sterile producer, authenticate native
run/artifact bytes, bind immutable source digest/profile/kernel, partition/LUKS
layout, fstab/kargs, installer/hook and bootloader bytes, actual tool and firmware
identities, and first boot/update compatibility. Test credentials must be injected
per overlay without captured private keys or recoverable reusable secrets; disk
free-space and deleted blocks require scrutiny. Disposable CoW overlays alone do
not sanitize their parent. A raw/QCOW2 builder must first demonstrate encryption,
fstab/karg and Secure Boot equivalence to the installer. Until those obligations
are proven, fresh disposable installation is the supported path.

## Functional selection shadow

`scripts/ci/functional-selection.py` does not select the bootability job and cannot
skip any existing test. `full_suite=true` explicitly selects all functional suites
in its report. Actual split functional jobs and savings are deferred until this
advisory boundary is validated. The tests live in the normal required bluebuild
contract check as well as the dedicated pilot contract job. Changing selector,
workflow, test infrastructure or unknown sources selects every functional suite.
No branch protection setting is changed by this draft.

The selector compares exact Git commits, resolves lock nodes through exported
input paths and `follows`, and records old/new immutable revisions, nar hashes and
versions available in `locked` (including Foundation's Home Manager/nixpkgs).
Node renaming alone does not select suites. Missing objects, cyclic follows,
malformed locks and unavailable diffs fail closed to all suites. Every selected
suite has a reason in the report.

| Change boundary | Advisory suites and reason |
| --- | --- |
| Resolved Home Manager input version | HM; does not itself select Homebrew |
| Determinate Nix runtime lock | HM and Nix lifecycle; HM runs on this runtime |
| Finite HM scaffold, template, scripts/home | HM; exported home initialization behavior |
| Foundation reviewed browser/desktop/home/shell modules | HM when exact source delta is available |
| Foundation brew policy/bootstrap/migration helpers | HM and Homebrew; HM activation checks brew providers |
| Foundation shared scripts, library, flake/module composition or unknown files | All; can change bootstrap and multiple exports |
| nixpkgs versions | All conservatively; evaluated HM and shared brew helper dependencies can change |
| Shared first-boot/services, base-image recipes/locks, unknown changes | All applicable suites; shared runtime impact |
| Documentation/test-only paths | No new functional execution; protected contract jobs still run |
| Any opaque Foundation source delta or incomplete input graph | All; no false-negative skip |

The exact Foundation delta can be supplied with `--foundation-repository` pointing
to a checkout containing both locked revisions; the tool uses immutable Git
objects and never that checkout's working files. It validates closure-labs source
identity before inspection. The initial hosted workflow deliberately does not
fetch Foundation source: a changed Foundation revision therefore selects all
until that delta is available. The real consumer copies Foundation into the image,
uses `lib.mkConsumerTemplate`/`mkHomeConfiguration`, then delegates `home-init` to
Foundation's `scripts/home.py`; Foundation also exports brew policy and bootstrap.
It is unsafe to classify an arbitrary Foundation bump as HM-only. These narrow
path mappings are advisory hypotheses, not a proof of Nix evaluation closure.
Before using them to skip real suites, compare evaluated exported behavior and
validate the protected corpus against representative Foundation/nixpkgs/HM
updates; an opaque mismatch must select all and block any skip.

## Local validation

Run the two new Python test files, `bash -n` for the three touched shell helpers,
and the existing VM-upgrade, qualification, validation-preflight and dependency
contract tests. Fixtures reject fallback, wrong digest/kernel/profile, staged-only
updates, emergency userspace, missing encrypted root/var, missing readiness,
malformed/incomplete receipts, ambiguous dependency graphs and hidden shared
changes. Hosted results and authenticated artifact IDs belong in the PR report;
this document itself makes no hosted-pass claim.
