# Foundation stage timing observations

Foundation's opt-in `FOUNDATION_TIMINGS=1` observations are retained by the
existing VM guest timing collector. The qualification initializer still runs
once, with the existing profile, stdin isolation, inherited Nix configuration
and resource limits. Its stderr joins the same streamed SSH output so timing
records reach the collector; the SSH pipeline and guest exit traps preserve
initialization failures. No additional initialization, evaluation or VM round
is introduced.

The guest receipt keeps its schema-1 `stages` array. An optional `foundation`
envelope contains schema 1, valid `stages`, and `rejectedRecords`. Legacy helpers
emit no envelope; the read-only report retains `foundationTimings: null`, rather
than inferring a miss, zero cost or successful instrumentation.

Accepted records have the exact versioned Foundation fields and fixed stage
names covering initialization, profile validation, Home Manager realization,
Brew policy/bootstrap/provisioning, commit/activation and rollback activation.
Each recognized line is capped at 1 KiB; at most nine unique stages can survive.
Elapsed time is finite and bounded to one day, timestamps require a timezone,
and status/outcome combinations must agree. Unknown fields, arbitrary labels,
malformed JSON, duplicate fields/stages and oversized lines are rejected. The
fixed rejection counter saturates at one million. Valid partial observations
remain available; optional diagnostic write failures do not replace guest status.

The existing native phase artifact retains the receipt, including failed phases.
The cost reader applies its 16 KiB VM-receipt cap and existing bounded archive
authentication. It binds the member to the exact native job/profile/phase and
attempt, rejects conflicting envelopes, and keeps rejected-record counts.
Foundation observations grant no reuse, approval or publication authority.

Validated observations also appear as nested `foundation-*` stages in cost
reports. Initialization, provisioning and commit totals overlap their children;
never add those intervals to each other or to native runner cost. The original
timestamp is retained as `guestStartedAt`, not host `startedAt`: guest clocks
cannot establish a host critical-path contribution. That contribution remains
unknown. Internal Nix evaluation/fetch/build and Flatpak readiness remain inside
their parent stages until separately measured.

[Foundation #23](https://github.com/closure-labs/foundation/pull/23) merged the
producer instrumentation. [Foundation v0.4.1](https://github.com/closure-labs/foundation/releases/tag/v0.4.1)
is published, and this candidate pins its reviewed immutable source. Both profiles'
fresh-install and upgrade/rollback qualification remain required before adoption.
Earlier v0.3.3 mains legitimately supply no Foundation timing records; an upgrade
that initializes an older predecessor can also retain that unknown observation.
The VM wrapper remains a qualification generation input; the first updated
context can conservatively miss predecessor reuse. Do not relax that identity
or claim observed production diagnostics from fixtures.
