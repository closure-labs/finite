# Workstation remediation validation — 2026-10-27

The baseline is QA-workstation-reboot-2026-10-27.md. This receipt distinguishes
implemented source fixes, applied workstation changes and unperformed rollout.
Unrelated existing work in the user's original checkouts was left untouched.

## Source validation

| Check | Status | Command / result |
|---|---|---|
| Foundation fixtures | passed | `bash tests/check.sh` — Foundation checks passed |
| Foundation controller | passed | `python3 -B tests/test_home.py` — 48 tests, OK |
| Host preflight | passed | `python3 -B tests/test_password_manager_requirements.py` — 14 tests, OK |
| Brew preparation | passed | `python3 -B tests/test_bluefin_preparation.py` — 7 tests, OK |
| Main-delivery policy | passed | `python3 -B tests/test_main_delivery.py` — 5 tests, OK |
| Feature discovery / CI planning | passed | `test_feature_graph.py` — 1 test; `test_ci_plan.py` — 13 tests, OK |
| Nix evaluation | passed | Resource-bounded `nix flake check --no-build --no-update-lock-file` |
| Real Nix contract builds | passed | `password-managers`, `ci-graph`, `consumer-template` check targets |
| Full personal candidate | passed | Immutable Foundation source commit 7f1aa0e; activation package built without installing it |
| Finite source proposal updater | passed | `python3 -B tests/ci/foundation-update.py` — 17 tests, OK |
| Finite command integration | passed | `python3 -B tests/home/foundation-integration.py` — 34 tests, OK |
| Administrator helper | passed | `tests/workstation/password-manager-setup.py` — 22 tests, OK |
| Desktop migration | passed | `tests/bluebuild/desktop-integration.py` — 15 tests, OK |
| Existing image contracts | passed | `tests/bluebuild/contracts.py` — 5 tests, OK |
| Text and whitespace | passed | `bash tests/repository/text-style.sh`; `git diff --check` |

Review caught and repaired the wrapped-package helper alias protocol, top-level
regular store JSON handling, GID0/missing-closure preflight cases, linked camera
ancestors, parsing exact approved bytes, and restoration after relabel failure.
The native security wrapper was separately built and executed against an inert
ELF test helper. This does not substitute for the browser handshake test.

## Applied workstation changes

The operator explicitly installed the reviewed helper. Read-only verification:

```text
$ password-manager-setup status --requirement <canonical-store-requirement>
{"installed": true, "hostPath": "<versioned-root-owned-helper>"}
$ stat -c '%U %G %a' <versioned-root-owned-helper>
root onepassword 2755
```

The exact approved helper SHA-256 is
`84a9ccc63e1d172b7ed94c98cc42b15cb5debb4a264b5daae4d9bbb237a3cb0f`;
the native wrapper SHA-256 is
`e9aa6e91367450e317fe5bf834f645363d75b3d4127b18d666cb275612b2223b`.
Independent review approved this explicit initial installation. Removal requires
quiescent Home Manager operations; concurrent removal/activation is unsupported.

The active Firefox and Chromium manifests now reference that helper, preserving
all original extension allowlists. Exact originals were backed up in the user's
private workstation-remediation state directory. These two files are a bounded
migration bridge; the shared aspect assumes declarative ownership when its
containing Foundation source is adopted. Other browser profiles were preserved.

Gear Lever's native Nix autostart was built and activated, retaining its supported
`--fetch-updates` behavior. The unused Claude handler and only its `claude-cli:`
MIME association were retired. The current profile JSON exactly matches the
pre-cleanup backup; roles, capabilities, packages and identity did not change.
All affected unmanaged files and the consumer have rollback copies.

Real final-candidate preparation passed with
`HOMEBREW_BUNDLE_NO_UPGRADE` explicitly unset. The candidate's packaged command
reported `Foundation 0.5.1 is current` for `foundation home update --check`.
The live consumer continues to select its existing qualified main source; no
unmerged source or new OS deployment was silently adopted.

## Browser acceptance follow-up

The operator restarted Firefox and 1Password, but the extension reported a
yellow connection problem. Desktop logs showed `invalid group attempted to
connect` and `PipeAuthError(NoCreds)`. BrowserSupport verified Firefox, then its
desktop connection was reset. The installer had incorrectly used system
`groupadd`, assigning GID 946; 1Password requires a GID greater than 1000.

The source installer now uses ordinary `groupadd` and validates the GID after
creation and during installation/status, including idempotent installations.
Foundation preparation applies the same threshold. Regression coverage rejects
946 and 1000 and accepts 1001. The administrator helper's 22 tests and
Foundation's 14 preflight tests pass. The earlier installed/status result did
not establish a working browser handshake.

Host inspection confirmed `root:onepassword` mode `2755`, GID 946, an empty
group membership list, and GID 1001 available. The operator was given bounded
`groupmod`, `chgrp` and `chmod` repair commands. Repair execution and successful
browser handshake remain unconfirmed. The approved helper binaries and hashes
are unchanged. Integration toggling removed native manifests; the two active
manifests were restored from the generated candidate with allowlists preserved.

## Rollout limits

### PR #308 CI follow-up — 2026-10-28

The hosted home-contract check failed before exercising three dispatch cases:
the tests replaced the Nix toolchain PATH with `os.defpath`, where Bash is absent
in the build sandbox. The fixtures now resolve Bash from the test toolchain and
use a fixture-only child PATH, preserving isolation from any installed Foundation.
All 34 command integration tests passed both normally and in a namespace without
`/usr` or `/bin`, using cached Nix-store tools. This is focused regression evidence,
not a full hermetic aggregate or assembled-image result.

The source proposal updater now has 19 passing tests, including an empty canonical
CI inventory (wait without adoption) and main advancing during the lock update
(restore all three proposal files). No qualification checks were weakened.

Foundation #32 has merged at `5c0cd8d0fcb96613780ce7ac77e3fa4630558cea`;
its canonical main CI run `40622556987` passed. Finite's pin remains unchanged:
the qualified proposal updater has not run with its required GitHub CLI access
in this executor. Source adoption and the separately authorized consumer update
remain pending; a green upstream run alone does not establish either.

| Acceptance | Status | Remaining action |
|---|---|---|
| 1Password desktop/extension handshake | failed | Correct GID 946, restart app/browser and confirm connection |
| Containing Foundation main adoption | not_run | Run the qualified proposal updater with GitHub CLI access, review the pin change, then authorize the consumer update |
| Finite assembled images and deployment | not_run | Hosted image validation and separately authorized rollout |
| Global camera migration and physical capture | not_run | Use reviewed operator helper/new image; verify capture/WebRTC/resume/reboot |
| Extension state on corrected image | not_run | Verify Custom Command Menu after image rollout |

Keep the working user camera override and the temporary personal Brew wrapper
until their containing source/image replacements pass on the workstation. The
Bitwarden ownership warning remains documented; mutable vault/settings were not
rewritten. Recovered login portal/keyring messages are not cleanup targets.
