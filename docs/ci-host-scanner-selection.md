# Host scanner changes do not rebuild OS images

The exact host scanner inventory in `impact.HOST_SCANNER_ONLY` uses the existing
controller-only route: source/runtime and scanner checks stay required, while OS
assembly is not selected solely for those files. It includes the Gitleaks installer,
its fixture/history workflows, six scanner helpers and three reviewed history-data
files. It does not exempt an entire directory or shared setup-nix/image workflow.

In [queue run41597662265](https://github.com/closure-labs/finite/actions/runs/41597662265),
scanner-installer PR #367 independently staged both
profile payloads. Finite staged for 23m52s then assembled for 8m14s; its VM step was
correctly skipped. These costs do not validate scanner behavior. The already required
source contracts and real pinned scanner fixtures do. This change removes those
image jobs for future scanner-only changes; no before/after wall-clock gain has
been measured yet.

Regression tests keep unknown siblings conservative and preserve recipe, lock,
image-workflow and shipped-file mixed changes. A dependency guard rejects a new
Gitleaks consumer in image/publisher/other jobs or local setup actions, and rejects
scanner imports in shipped files or the image payload expression. Such a new consumer
requires reexamining the exact inventory, rather than silently inheriting an exemption.
Incoming scanning, historical scanning, approval, signatures and security admission
are unchanged. Changes that actually select images retain the existing merge-group
integration and VM requirements. No extra image/VM cohort was dispatched for this investigation.
