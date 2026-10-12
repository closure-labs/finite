# Daily-driver roadmap

Finite's near-term goal is a reliable personal workstation with recoverable
updates. BlueBuild owns the OS image, Nix stages pinned payloads, and Home Manager
owns user composition. Keep these boundaries and the four existing profiles.
Additional hardware is best effort until a release records physical test results.

## Build sequence

| Order | Deliverable | Exit evidence |
| --- | --- | --- |
| 1 | Exact-digest qualification and consistent delivery policy | Failed, missing or mismatched acceptance cannot promote; queue deadlines accommodate validation |
| 2 | Encrypted-root installation, upgrade and rollback | Hosted Secure Boot/LUKS evidence for each published profile; previous public digest retained on failure |
| 3 | Desktop hardening and visible app maintenance | Keyboard access is an explicit administrator choice; approved app-input differences are visible without changing user pins |
| 4 | Qualified daily-driver release | Signed durable assets, retained rollback deployment, and the physical checklist on the actual workstation |
| 5 | Measured CI optimization | Five equivalent warm runs and one cold run, with queue, evaluation, transfer, build and qualification costs separated |

Each milestone follows the preceding safety work. Local regression tests do not
establish that hosted qualification or physical hardware works. Record missing
evidence explicitly and link successful run IDs and image digests before marking
a milestone complete.

## Support and scope

The maintainer owns the personal workstation's update review and recovery.
Record image digest, firmware, hardware model and test date with release evidence.
Use the [physical checklist](workstation-qualification.md#physical-hardware-checklist)
for suspend, power, displays, connectivity, media, authentication and persistence.
Retain the previous working deployment before changing kernels or channels.

Keep next-kernel profiles until the upstream Bluefin kernel passes the same boot
and Dell hardware checks. Do not add roles, foundations or hardware claims without
a concrete user need and acceptance criteria. Fleet management, public support
SLAs and new paid CI infrastructure are outside this milestone.

## Maintenance and performance

System image updates and user application updates have separate owners and state.
Preserve custom Home Manager inputs and pins, report approved-input differences,
and build manual updates before activation. Inspect inherited Homebrew/Flatpak
update services on the installed image before assuming they cover every app.

Preserve signature checks, exact tested/published digests and conservative
selection during optimization. Capture runner image, source/base digest, cache
state and phase timings. Choose improvements from the largest measured cost;
instrumentation alone is not evidence of savings. Keep baseline reports dated
and distinguish implemented changes from verified hosted results.

Local implementation uses the [jj contribution workflow](development.md#choose-where-to-make-a-change).
