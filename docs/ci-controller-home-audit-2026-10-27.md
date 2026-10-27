# Controller recovery and home architecture audit, October 27 UTC

This audit uses the [successful production rollout](ci-foundation-production-2026-10-27.md),
read-only registry inspection, the decision journal and two retained native fresh
job logs. The [snapshot](ci-controller-home-audit-2026-10-27.json) binds candidate
identities, journal inputs and log hashes. No local Nix, VM benchmark or package
ownership change was performed.

## Follow-up dispatch is redundant

[Run 40535098249](https://github.com/closure-labs/finite/actions/runs/40535098249)
was dispatched by Decider with decision marker `cc4b1c48a7f3…`. The journal binds
it to profile finite, origin run 40474776795 and old digest `sha256:2420c56d…`.
That origin was blocked before signing. It is not a request to qualify a newly
changed application payload.

Meanwhile, scheduled run 40521333174 qualified and promoted `sha256:4fb99462…`.
Live finite/latest channel inspection confirms that newer candidate and source
`3125b26c6087b9394f8ff42a3120fd03a596289e`. The immutable old candidate and the
newly qualified candidate share build identity `v1:3a09bf6f…`. The finite-dev
channel likewise matches the separately qualified/promoted candidate. Full
identities are preserved in the snapshot; abbreviation here is descriptive only.

The controller checks incomplete publishers before journal claim and before
POST, and recovers ambiguous responses with a CAS journal. Those safeguards
prevent competing dispatches and duplicate POSTs for the same request. They do
not check whether an independent publisher already satisfied the requested
profile. After the scheduled run completes, the old decision request can still
resume its original candidate. This is a confirmed missing completion check.
The redundant finite recovery was cancelled before another qualification round;
GitHub confirmed cancellation. Its consumed work must remain in later cost reports.

### Required remediation

Add an authenticated already-satisfied check after live decision authority and
before journal claim/dispatch, then recheck before POST. A registry label or
matching input hash alone must not suppress recovery. Require a trusted successful
native publisher, immutable promotion/qualification artifact digests, correct
repository/workflow/profile/ancestor source and acceptance binding, and matching
current public aliases. Any accepted successor must have the same exact build
identity, fresh security/admission under the active decision and completed required
qualification. Journal the independent satisfaction proof separately from an
actual dispatch; do not fabricate a request-marker run or rewrite frozen packets.

Missing, stale, mismatched, revoked or ambiguous evidence retains normal recovery.
Tests must cover unrelated publishers, wrong profiles, stale aliases, partial
promotion, source changes, revocation, expired evidence, contention and lost
responses. The guard remains a proposed implementation; no production controller
policy was weakened in this audit. The analogous finite-dev follow-up 40537674162 was subsequently queued. Its
journal bound the same old origin, and immutable candidate inspection matched
the already promoted dev build identity. Cancellation was requested while it was queued after
those checks; GitHub briefly transitioned it to running, so force cancellation
was also requested. Cancellation alone is not a durable fix.

## Refined measurements from existing logs

Fresh realization took 157.6/177.5 seconds. Its retained output contains
1,262 substitute-copy messages per profile and 102/101 build messages. These are
message counts, not unique paths or timings. They establish substantial closure
activity; they cannot split evaluation, substitution and local builds. Keep one
`nix build` rather than adding another evaluation merely for a stopwatch. Next,
use bounded version-aware structured activities to observe overlapping evaluation,
transfer and build work; retain unknown coverage and existing retry/exit behavior.

Brew bootstrap took 141.8/156.3 seconds and reported installation of 20 formulae
plus its tap. The installed-policy checker batches `brew list`, rather than
running a lookup per package; its activation check's log-arrival window was only
0.053/0.056 seconds. Removing that guard is not a plausible major saving.
Next measurement boundaries are precheck, bundle installation and postcheck,
with resolved package/bottle identities and cache state retained separately.

The activation logs substantially narrow the 103.8/133.9-second totals:

| Log-arrival interval / seconds | finite | finite-dev |
| --- | ---: | ---: |
| reloadSystemd to next activation hook | 102.618 | 132.331 |
| flatpak-managed-install hook to next hook | 0.006 | 0.009 |
| installPackages to next hook | 0.542 | 0.845 |

Both logs say `Starting units: flatpak-managed-install.service` inside the long
reloadSystemd interval. This points to synchronous service startup, not the small
subsequent activation hook, as the next audit boundary. Transport and buffering
mean these are log-arrival windows, not monotonic service durations or causal
CPU measurements. Add optional bounded timing around the actual service job and
Flatpak operations before adopting concurrency changes. Preserve application
readiness acceptance even if a future design makes initial activation asynchronous.

## Architecture and best-practice assessment

**Retain bootc for OS content and Home Manager for personal state.** bootc's
[filesystem model](https://bootc.dev/bootc/bootc-filesystem.7.html) separates the
immutable image from persistent mutable data. Build OS packages/services into
`/usr`; do not assume changing files under a built `/var/home` will update an
existing user's state. Nix store/profile and user Flatpak state have their own
lifecycles; an OS rollback is not automatically a Home Manager or application
rollback. Finite's explicit persistence and rollback checks are necessary.

**The Nix realization interface is appropriate.** The
[documented build command](https://nix.dev/manual/nix/2.33/command-ref/new-cli/nix3-build)
realizes or substitutes the activation closure. A pinned lock and one realization
followed by actual activation are preferable to repeated ad-hoc `nix profile`
installs. Direct activation is supported by Home Manager, including its
[collision/backup configuration](https://nix-community.github.io/home-manager/usage/dotfiles.html).
Preserve those checks and the activation DAG; do not parallelize arbitrary hooks.

**Resource-control scope needs correction in documentation and measurement.**
Foundation wraps the client in a user scope with MemoryMax=5G, MemorySwapMax=512M
and CPUQuota=100%, and requests max-jobs=1/cores=1. Those scope limits do not
establish a global cap on work executed by the separately managed root daemon.
The checked-in daemon unit has no matching MemoryMax/CPUQuota. Nix's
[job/core settings](https://nix.dev/manual/nix/2.31/advanced-topics/cores-vs-jobs.html)
control build concurrency, not a hard bound on all evaluation, copying or daemon
resource use. The [multi-user Nix manual](https://nix.dev/manual/nix/2.34/installation/multi-user)
confirms that store operations are forwarded to the daemon.
Measure client and daemon cgroups separately. Preserve current
limits; a service/slice policy requires multi-user and boot acceptance rather than
an unmeasured global limit change.

**Brew ownership is coherent but less reproducible than the locked Nix path.**
The [Brew Bundle documentation](https://docs.brew.sh/Brew-Bundle-and-Brewfile)
describes declarative installation, supports no-upgrade operation and explicitly
has no complete Brewfile lock mechanism. Finite correctly disables automatic
updates and uses `--no-upgrade`, but a cold install can still resolve a different
formula/dependency closure later. Installed-presence checks do not pin versions.
This differs materially from a lock-bound Nix closure.

Evaluate one owner per CLI: OS-required tools can be built as RPMs into the bootc
image; personalized tools can live in Home Manager's locked Nix packages. The
current Bluefin-aligned Brew selection is intentional and should not be reversed
blindly: moving its 20 formulae to Nix might increase store transfers or builds.
A representative package-ownership comparison must include image size, cold
install, update/security cadence, shell precedence and both-profile acceptance.
Do not install the same user-facing CLI through all three managers.

**Keep Flatpak native state explicit.** A systemd-managed installation job is
reasonable; synchronous network installation on every fresh activation is a
latency tradeoff. First distinguish transport from installation and no-op checks.
An asynchronous service can improve perceived login time only with explicit
readiness/failure reporting. Baking defaults into `/usr` does not make mutable
Flatpak installations bootc-transactional. Keep fresh-install coverage unseeded.

## Recovery guard implementation

The completion verifier now joins a successful trusted main publisher to exact
profile/build identity, source ancestry, successful sign/security/qualification/
promotion jobs, digest-authenticated native archives, current qualification
inputs, encrypted Secure Boot acceptance and desktop evidence. It revalidates
fresh native security, live decision coverage, the image signature and every
public alias. Registry labels alone cannot satisfy a request.

Checks run before a CAS claim and again immediately before dispatch. Missing,
stale, revoked, malformed, mismatched or ambiguous proof retains recovery. The
lookup is bounded to ten recent successful publishers. A schema-2 `satisfied`
journal records immutable publisher/artifact identities separately from schema-1
claims and dispatches; every subsequent reconciliation reauthenticates live proof.
Existing dispatched records and lost-response discovery retain their semantics.
Frozen decisions and historical packets are unchanged.

The cancelled follow-ups 40535098249 and 40537674162 consumed **776 runner
seconds combined**. This is incurred cost, retained from the supplied audit
accounting; no avoided cost or recurring savings has been measured. Source tests
do not establish production rollout or new qualification.

The final source audit additionally binds satisfaction to the production
`image_identity` contract for the exact current hosted checkout. Agreement
between an old request and an old publisher is insufficient after current image
inputs change, even when every source remains on the same ancestry chain. A
missing current identity is a normal recovery miss. This hosted eligibility
evaluation is independent of user realization instrumentation; it does not add a
second Home Manager realization or claim performance savings.
