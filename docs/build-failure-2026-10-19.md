# Build failure RCA: 2026-10-19

The [scheduled build](https://github.com/closure-labs/finite/actions/runs/39279001307)
at revision `feb7c88e70d53f4b312d5a462a98aef33ee9e48d` assembled both images
and passed Nix/runtime contracts. Both publication security jobs then exited 2
before scanning. Signing, qualification and promotion were skipped.

## Scheduled inventory consumer rejected

`reuse-image-inventory.py` allowed `build.yml` consumers triggered by `push` or
`workflow_dispatch`, but omitted `schedule`. The production build workflow
supports all three events and had inventory reuse enabled. Its scheduled jobs
therefore failed the consumer trust check:

```text
Inventory reuse rejected: Inventory reuse requires a trusted hosted main image consumer
```

The allowlist omission dates to `d15eb999`. The same error occurred in the
[October 18 scheduled build](https://github.com/closure-labs/finite/actions/runs/39127913025)
before the dependency update merged. Retrying the unchanged scheduled run
cannot repair it.

The fix allows scheduled consumers of the exact main-branch Build Finite
workflow. Repository, workflow, branch, commit and artifact authentication remain
required. Inventory reuse still requires a new vulnerability scan, database
refresh and current policy evaluation. Tests now exercise authenticated retrieval
for push, manual and scheduled consumers and reject PR/merge-group consumers.

## Upgrade qualification blocked by legacy fixture

The [manual build](https://github.com/closure-labs/finite/actions/runs/39204259709)
passed security but failed both upgrade qualification jobs with:

```text
Foundation: Configuration already exists; use finite-home-migrate or finite-home-apply
```

The predecessor preparation helper created `home-manager/customize.nix` before
calling `home-init`, to extend an older scaffold's activation timeout. Foundation
initializes its configuration transactionally and rejects any existing target
directory. Adopting Foundation in `5219577e` left this legacy fixture behavior
in place. Fresh-install qualification does not invoke the predecessor helper.

The helper now detects the installed Foundation metadata and leaves its
configuration directory uncreated. Foundation already provides the longer
activation timeout. Historical images retain the existing override, and tap
trust setup still runs for both generations. Fixtures cover both generations,
failed tap trust and preservation of existing customization.

## Validation and recovery

Focused inventory authentication, scanner policy, predecessor preparation,
qualification and VM transfer fixtures validate the changes locally. Image and
VM operations must run on GitHub-hosted runners. A successful PR contract check
does not establish production security or VM qualification: both publication
profiles still require the normal security, signing, fresh/upgrade qualification
and promotion gates after the fix reaches main.
