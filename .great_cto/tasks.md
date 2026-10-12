# Security audit implementation

## Current desktop continuation

- User approved host ZFS removal across all four profiles ("dump zfs"), in
  addition to optional generic virtual-camera removal. Remove only reviewed ZFS
  package names; preserve signatures, unrelated RPM inventory and file ownership.
- Host ZFS is no longer supported. A separate FreeBSD VM storage setup is the
  user's proposed alternative, not validated guidance or a host-root replacement.
- Draft PR #144 targets main; its last posted head starts 9a65. Runtime source
  is changing; final source revision and new validation run bindings are pending.
- Historical source contracts38317182847 passed4bc79ded; these do not validate
  the new ZFS-removal source. Run fresh focused/source/Nix contracts and all four
  profile builds after cheap checks; obtain one useful changed-candidate scan.
- Failed guarded representative38314613864 and ownership38315879860 remain
  historical evidence, not successful image/native/boot results. Matching ZFS
  publisher modules are no longer the chosen product prerequisite.
- Next301 testing preference is still unapproved. Keep next300 and exact
  f45/f45-updates policy; October XFS/AMD security gap remains explicit.
- Fresh prerequisite38314613864 still found approved AnyIO/msgpack/rclone fixes
  unavailable. Other Go/Tailscale/Sigstore rebuild requirements remain blocked.
- Preserve complete Go38310504908 evidence, actual Cosign3.1.3 partial bundle fix,
  earlier kernel/package runs and previous all-profile integration as scoped history.
- PR140 merged1bf562527742 and PR143 mergedbe90c0a83126. No new merge or
  publication is authorized; maintain isolated Jujutsu desktop-security workspace.
- Heavy work stays hosted; no workstation Nix compilation/image scan/VM build.
  Baseline finding statuses and symbol/module/stdlib unknowns remain unchanged.
- Current plans and pending evidence: docs/desktop-security-validation-plan.md,
  docs/generic-kernel-remediation-plan.md and
  docs/desktop-security-evidence-2026-10-12.json. Source/build pending for changed
  code; vulnerability clearance blocked; release ineligible until all gates pass.

User authorized implementation of the 2026-10-12 cybersecurity report using
great_cto and nixos-managing. Existing product choices remain: personal daily
driver, automated qualified images, manual application updates, opt-in raw
keyboard access, shared read-only audit App, and Jujutsu repository workflow.
Beads is unavailable; this file is the skill's task-tracking fallback.

| Phase | Owner | State | Completion evidence |
| --- | --- | --- | --- |
| Scope and architecture | root + security-officer | Approved by implementation request | Implement report treatments; isolate signer; preserve immutable qualification |
| R1/R6 publication controls | security_delivery | Implemented | Digest-bound scan policy and isolated signer |
| R2 live settings audit | security_settings | Validated: full CLI + partial App | Complete normalized settings and negative fixtures |
| R3/R4 runtime controls | security_runtime | Implemented | SELinux reconciliation and cloud-init disabled by default |
| R5 upstream trust | root | Implemented | Reviewed publisher key and negative signature tests |
| Integration and documentation | root | Implemented; hosted contracts pass | Pinned Nix checks, runbook and residual requirements |
| Independent code/QA/security review | specialists | Approved | No blocking source findings; focused suites passed |
| Hosted validation and deployment | root | Four-profile validation passed; release blocked by policy | PR #139; CLI/App audits, hosted Nix/runtime checks and native extraction preflight pass; real native inventory + authenticated Grype continuation find 281 unique fixable High/Critical component/advisory pairs |

Operational constraint: after workstation memory pressure, stop local Nix evaluations,
image scans and VM builds. Use hosted runners for remaining full validation.
Existing signing key migrated into image-signing and release environment secrets;
repository copy retirement remains pending old-workflow completion.

## Historical follow-up PR: scan remediation and CI tool reuse

User requested a new PR with Nix CI optimizations and the latest failed scan's
remediation. Work is isolated in Jujutsu workspace `security-remediation`, based
on PR #139; its existing change remains intact.

- Reuse pinned image tools once per job and use lightweight maintenance exports.
- Apply reviewed fixed-version floors to installed Fedora RPM packages only.
- Preserve all 281 component/advisory pairs in the remediation ledger.
- Keep Go, kernel, AnyIO and other unresolved findings blocked until rescanned.
- Run hosted cold/warm tool benchmarks and image validation before merge; local
  tests establish orchestration behavior only. No local Nix builds or image scans.

## Validation/remediation execution

- Planning: documented staged validation and acceptance criteria in
  `docs/validation-remediation-plan.md`; user explicitly authorized implementation.
- Performance QA: two hosted cold/warm benchmark pairs passed with lower setup
  time; artifact retention verified on second run. No more repeats needed.
- Security prerequisites: all 16 implemented RPM floors available, ownership
  mapped from the existing authenticated SBOM. AnyIO/msgpack/rclone fixes remain
  unavailable; explicit readiness probe correctly reports blocked, not error.
- CI remediation: cancelled doomed PR140 matrix after shared RPM parser rejected
  legitimate `gpg-pubkey` architecture `(none)`; exact exception and regression
  fixtures implemented. Validate actual transaction on one authenticated base
  container before restarting the full matrix.
- Independent QA/security: new prerequisite/ownership/diff helpers reviewed;
  summary comparisons are triage-only and never automatically resolve findings.
- Release remains blocked by unavailable owning-package fixes and unverified
  remaining Go/kernel findings. No broad suppressions or package overlays added.
- Focused transaction: run 38295423922 passed on the authenticated Bluefin base,
  including actual fixed-floor transaction and already-satisfied second run.
  Final matrix run 38295992049 passed all four image profiles, runtime inspections,
  documentation, Nix contracts and CI gate at f506ae341663; scan-readiness remains blocked.

## Historical continued validation and remediation

- Historical state at that stage: PR #139 merged and PR #140 targeted main.
  Both later merged; retain the passed matrices and two benchmarks.
- Hosted prerequisite refresh run 38299553401 completed with expected `blocked`
  policy result, not a probe error. All 16 floors remain available; approved
  AnyIO/msgpack/rclone fixes remain unavailable. Native inventory parser passed.
- Security-officer ownership follow-up identified a signed stable Tailscale RPM
  candidate. Hosted run 38299748350 verified exact package/key hashes, signature,
  identity and actual embedded Go modules. Separate installed-only update implemented.
- Investigate cosign provenance and exact kernel/platform applicability separately;
  no false-positive exemption or resolved finding has been introduced.
- Heavy work stays hosted. Source/build validation, vulnerability clearance and
  release eligibility remain distinct verdicts. No merge or publication authorized.
- Combined transaction run 38300150513 passed against the authenticated pinned
  generic base, then both helpers passed no-repository/vendor-access repeats.
- All 100 focused tests and source lint passed. Independent security and
  QA/performance/readability source reviews approved; final PR integration checks
  are recorded against the exact head on PR #140.
- Remaining external dependencies and their specific unblock evidence are listed
  in the plan. Baseline findings remain pending rescan; release remains blocked.

## Historical ZFS discovery before the support decision

- Run 38314613864 correctly rejected an old-tree ZFS module still owned by
  retained `kmod-zfs`; no candidate digest or scan was produced. Older passing
  blanket-prune runs do not establish ZFS functionality.
- Read-only current-base ownership probe 38315879860 passed and confirms both
  current approved bases retain `kmod-zfs` and its old-kernel module.
- At that stage only virtual-camera removal was authorized; ZFS removal was
  undecided and matching signed modules were unavailable. The user has since
  authorized removing host ZFS support across all four profiles.
- Shared ownership guard implemented for both kernel paths; 25 generic and ten
  next fixtures pass. Preserve
  all owned files and continue independent Cosign/CI/evidence work; avoid doomed
  image builds while this dependency remains.

- Next kernel transactions now enforce complete unrelated-RPM invariance after
  each DNF operation. Regression cases reject solver removal of both the ZFS
  package and module files before old-tree pruning.
- Validate frozen source contracts on a hosted runner independently of the
  known-blocked image matrix. No scan or boot qualification claim is made.

- Hosted full source contracts PASS: run 38317182847, exact checked-out source
  `4bc79ded4fcf4cfe0d426f9d0bca2f03800b34db`. At that point later edits were
  evidence only; the newly authorized runtime removal code now needs fresh checks.
- Before the decision, the image matrix was held on confirmed ZFS ownership;
  no new scan digest or boot/signing/release verdict resulted from that source.

- Draft [PR #144](https://github.com/closure-labs/finite/pull/144) targets main
  directly. Its prior posted head starts 9a65; keep it draft while new authorized
  removal code receives fresh validation. PR #143 is merged.

## Authorized host ZFS removal follow-up

- Removal decision completed for all four profiles; no further ZFS approval or
  matching-module wait is required for the chosen unsupported-host-ZFS direction.
- Fresh removal/invariance tests, source/Nix contracts, four-profile image evidence
  and changed-candidate native scan remain pending; root will bind exact revisions.
- Preserve the separate unapproved next301 testing decision and production
  security/signing/boot requirements. No automatic finding resolution or waiver.

## Blocker-resolution assessment

- Current focused validation: 44 kernel and 12 contract fixtures passed at source
  c295; later KEV non-waivability hardening has 30 passing policy fixtures.
- Representative hosted candidate38321177037 at frozen source371b7f17 is in
  progress; no new scan outcome, image clearance or boot success is claimed.
- Keep fix dependencies separate from applicability/exposure evidence and final
  source/build/security/release gates. No active exception or new testing approval.
- Next cheap investigations: msgpack owning consumers/Unpacker error handling and
  rclone dependencies/RC/S3 configuration before optional removal or exposure review.
- Existing exact digest/component/advisory exceptions expire within30days and need
  documented reviewer/reason; every matching location in that digest must support
  the review. KEV (including aliases/ignored matches) is now non-waivable with
  the active gate. Unknown symbols or SELinux labels are not blanket mitigations.
- Resolution options and evidence limits recorded in the desktop plan; reuse the
  changed-candidate result and avoid unchanged scan repeats or unsupported fixes.
