# Host scanner changes do not rebuild OS images

The exact host scanner inventory in `impact.HOST_SCANNER_ONLY` uses the existing
controller-only route: source/runtime and scanner checks stay required, while OS
assembly is not selected solely for those files. It includes the Gitleaks installer,
its fixture/history workflows, six scanner helpers and three reviewed history-data
files. The incoming scan now lives in the call-only reusable workflow
`incoming-secret-scan.yml`, also in that exact inventory. Its scanner steps and
exact-head/protected-base identities are unchanged. No image job consumes it.
It does not exempt an entire directory or shared setup-nix/image workflow.

The extraction edits `build.yml`, which remains a VM-control input. This PR must
therefore validate both VM profiles. Later changes confined to the reusable scan
keep source/security/real-engine fixtures but select no image or VM profiles.
Mixed scanner plus image, installer, VM harness or build-workflow edits retain the
existing conservative selection. Full VM tests for every edit to the central
build workflow are not a scanner requirement; this extraction removes the need
to edit that shared control file for scanner implementation changes. It does not
relax selection for arbitrary central build-workflow edits.

GitHub gives called jobs a combined caller/child name. A minimal native
`Repository security audit` compatibility job preserves the previous status name
and CI gate dependency; it requires the called scan's same-run result to be
`success`. Failure, skip, cancellation or missing output cannot yield green.
This adds one tiny runner job with no checkout/setup rather than a new status API
publisher or settings migration. No end-to-end speedup is claimed before measurement.

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
