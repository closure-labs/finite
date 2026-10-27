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

## Refined version-2 observations

The consumer accepts legacy schema-1 rows and bounded schema-2 detail rows in the
same optional envelope. Its allowlist now includes optional preparation, Bluefin
readiness/install/postcheck, bundle identity, Nix activity observations, separate
client/root-daemon resources, and actual service/Flatpak work. Each line remains
at most 1 KiB. The writer reserves a 14 KiB observation/receipt budget beneath
the unchanged 16 KiB reader cap. Malformed, duplicate and unknown records increment
the bounded rejection count while valid partial records remain available.

Only fixed detail keys survive: Nix start/stop activity counts and union/overlap
intervals; cgroup numeric counters and coverage; the inherited Brewfile hash and
cache presence. Raw paths, command arguments and arbitrary logger fields are
rejected. Incomplete intervals and unsupported evaluation boundaries stay unknown.
Resource rows distinguish the realization's client scope from shared root daemon
cgroups; client limits are not a whole-build cap. Snapshot rows' zero-length
observation intervals do not mean zero resource consumption.

These rows are diagnostics, never qualification or admission authority. Existing
103/132-second log gaps remain arrival windows, not exact service timings.
Producer deployment and natural qualification observations remain pending; source
fixtures do not establish a performance gain. Do not add extra evaluations or VM
rounds solely for a report, and keep matched warm/cold correctness and complete
cost gates for any subsequent reuse or concurrency proposal.
