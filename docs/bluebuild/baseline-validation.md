# Early BlueBuild sandbox validation

Historical implementation evidence from `closure-labs/finbox`, before Finite's
current two-profile layout. These runs record the original integration baseline.
Current development checks are in [Develop Finite](../development.md), and
production qualification is described in
[workstation qualification](../workstation-qualification.md).

| Check | Evidence |
| --- | --- |
| Four signed sandbox images and final-image assertions | [Build 34007974907](https://github.com/closure-labs/finbox/actions/runs/34007974907) |
| Four images built with read-only publication permissions | [Validation 33999999603](https://github.com/closure-labs/finbox/actions/runs/33999999603) |
| Generic ISO and UEFI acceptance | [ISO](https://github.com/closure-labs/finbox/actions/runs/34005801360), [VM](https://github.com/closure-labs/finbox/actions/runs/34006462352) |
| Next-kernel ISO and UEFI acceptance | [ISO](https://github.com/closure-labs/finbox/actions/runs/34006463272), [VM](https://github.com/closure-labs/finbox/actions/runs/34007158009) |

Both VM runs passed first boot, Nix/SELinux, Home Manager, signature rejection,
updating, persistence and rollback. The hosted AMD processors reported the
inherited `mcelog` diagnostic service as unsupported. Physical hardware checks
were a separate acceptance step.

Original upstream revisions are retained in
[reference-revisions.json](reference-revisions.json).
