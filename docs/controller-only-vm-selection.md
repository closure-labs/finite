# Controller-only premerge VM selection

The premerge selector exempts only these reviewed entry points from the broad
`scripts/bluebuild/` VM trigger:

| Path | Responsibility and callers |
| --- | --- |
| `scripts/bluebuild/prune-qualified-isos.py` | `cache-maintenance.yml` expires retained artifacts through the existing retention controller. |
| `scripts/bluebuild/audit-published.sh` | `image-security.yml` verifies and scans an already-published immutable image. |
| `scripts/bluebuild/publication-current.py` | Qualification preflight checks current-main ancestry and publication metadata. |

These entry points do not assemble OS or installer bytes or run guest acceptance.
They are already explicit exclusions in `image_identity.py`; the dependency
inventory categorizes them as policy/host controllers. That inventory is not a
complete runtime dependency proof: new behavior or new callers require review.

A change confined to these files still runs documentation and the complete
Nix/runtime/security source contracts. The merge-queue gate requires those jobs
to succeed and requires image/publication jobs to be explicitly skipped. Mixed
boot, installer, recipe, real lock, or VM-harness changes still select both
profiles. Unknown BlueBuild helpers remain conservative; renames retain both
paths through the existing `--no-renames` diff, so an unreviewed destination is
not exempt. Source contracts also require all three entry points to exist.

## Boundaries and risk

This changes only premerge work selection. It does not authorize publication,
weaken author/review requirements, change production qualification identities,
or expand reuse eligibility. Scanner implementation, qualification/reuse helpers,
and the VM harness retain their existing VM triggers. Failures to determine the
diff retain full validation.

The avoided work is structurally two image/installer/VM validations for a
controller-only change. No measured time or percentage saving is claimed; the
frequency of qualifying changes determines actual benefit. The principal risk
is an exempt file later acquiring guest/image behavior: maintain the exact list,
review its call sites when changing responsibilities, and remove the exemption
if that boundary changes. Do not infer a blanket exemption from the broader
image-identity qualification-only set.
