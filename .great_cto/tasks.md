# Security audit implementation

## Active release eligibility sequence

- PR147 head68fbf8759df3208dc6879640aa7d211d9162addf PASS all four image builds,
  runtime inspections, docs, pinned Nix contracts and CI gate38342366434.
  It incorporates externally merged Bluefin PR146/maincbaf8264 and adds the
  installed-only signed Curl12 floor, guarded candidate reuse and opt-in diagnostics.
- Changed standard/DX native diagnostics38341281199/38341284379 completed
  BLOCKED with valid scanner/probe evidence; no scanner errors or publication.
- Reuse all four new main38340112122 registry candidates. Compact comparison
  38344754471 and final full-native reevaluation38348146097 PASS evidence checks:
  original results reproduced and all observations preserved, no new image scans.
- Independent review approves51 exact scopes:36 Linux/fixed-Podman nonapplicability
  and15 accepted SSH large-write-loop availability risks;14dayexpiry. Go5017
  unreleasable connection leaks, Go6612 host-memory risks, other serious/embedded
  compiler/dependency risks and both Next kernel holds remain blocked.
- Signed reference proofs PASS: FreeRDP38340338218, Podman38344182246,
  HTTPD38344687698. Current HTTPD/FreeRDP matches are not observed and current
  versions differ from old references; no false fix claim or waiver follows.
- 401 focused fixtures pass; policy fixture argument-size error fixed with a
  temporary policy file. Stacked PR148 passes source/docs/Nix/payload/CI gate
  38349399433 and skips redundant image work, reusing validated PR147 builds.
- Current blockers: standard87pairs/266records; DX135pairs/481records; Next hold.
  Source/build PASS for PR147. Vulnerability clearance BLOCKED. Release INELIGIBLE.
- Plan/evidence/owners: docs/release-eligibility-sequence.md,
  docs/release-eligibility-evidence-2026-10-12.json,
  docs/current-desktop-risk-blockers-2026-10-12.json. Reuse dated approved metadata;
  await concrete publisher fixes/rebuilds or complete specific artifact/resource proof.
- Heavy work remains hosted; original user workspace preserved. No merge/release
  publication. Temporary read-only validation branch is removed after retaining
  exact source/run/report evidence. Original user workspace remains untouched.

## Completed desktop policy continuation

- User-approved host ZFS removal is implemented and validated across all four
  profiles: remove only kmod-zfs, zfs and python3-pyzfs; retain required shared
  libraries, unrelated inventory and file ownership. Host ZFS is unsupported.
- PR #144 head `fd64b32f4667b3f366b2eafcba5c6ed9ba6431dd` passed all four builds,
  runtime inspections, documentation, pinned Nix/source checks and CI gate in
  [run 38322036024](https://github.com/closure-labs/finite/actions/runs/38322036024).
  Tested PR merge revision: `ed7e5151f51445f4cd5e64715b6e9cef80115600`.
  Image artifacts record local Docker identities; no registry publication,
  production signing, merge or VM boot qualification is claimed.
- Representative native run 38321177037 completed at `371b7f17bc02` with 261
  distinct old-strict blocking pairs, 725 records and zero observed KEV records.
  Its transaction and offline repeat passed. Recovery run 38324348014 passed
  configuration semantics, ordered 89-layer/SBOM binding and exact comparison
  without another build/scan. Diagnostic evidence remains release-ineligible.
- Older FreeRDP/HPLIP/libX11/sudo ELF matches map to retained OSTree object paths;
  live RPM catalog entries show implemented floors. Reachability/backport
  applicability remains unknown; no false-positive or fixed disposition follows.
- User approved upstream-maintained-risk: ordinary inherited risks remain visible
  advisories under an independently authenticated baseline. There are 45 serious
  groups/102 aliases; KEV, reviewed serious risks and untriaged Critical block.
  No active reviewed proof dispositions or suppressions. Finite overrides remain
  separately accountable. Policy-only follow-up PR145 targets main; retained evaluation38327429782 completed blocked; final hosted source checks passed38327424786. PR144 was merged externally at bd78c07f2541 while this follow-up was being prepared; no merge was performed by this continuation.
- Latest policy-only integration review approved; 212 focused tests passed
  (66 policy, 43 upstream, 35 reliability, 23 local-candidate, 16 selection,
  14 comparison, 11 approved-baseline and four delivery fixtures). Root will bind
  this source to its new PR and hosted run; it is not a current clearance verdict.
- Identity self-hash/exclusion correction causes one computed-identity migration
  requiring main reconciliation once; subsequent policy-only edits retain stable
  build identity. Historical fd64 and native candidate identities stay unchanged.
- Next 300 remains pinned; fixed 301 testing choice is unapproved. Exact stable
  f45/f45-updates source hold remains release-blocking until approved fixed source,
  signed/module/initramfs evidence and affected-profile boot qualification.
- Historical prerequisite run 38314613864 remains a dated metadata observation:
  AnyIO/msgpack/rclone fixes unavailable then; no current availability claim or
  repeated polling. Ordinary msgpack process DoS is advisory under the new mode;
  AnyIO TLS and rclone serious conditional risks still require precise review.
- Preserve Go run 38310504908 unknowns and actual Cosign 3.1.3 partial bundle fix.
  PR #140 merged at 1bf562527742 and #143 at be90c0a83126; these were separately
  authorized. No new merge/publication is authorized. Use the isolated JJ repo.
- Heavy builds, full SBOM/image scans and VMs stay hosted. Reuse evidence and
  benchmarks. Current verdicts: source/build PASS for PR #144; new-policy security
  evaluation38327429782 completed BLOCKED(121pairs); release INELIGIBLE. Plans/ledger preserve exact scope.

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

## Completed authorized host ZFS removal follow-up

- Removal decision completed for all four profiles; no further ZFS approval or
  matching-module wait is required for the chosen unsupported-host-ZFS direction.
- Fresh removal/invariance tests, source/Nix contracts and all-four image evidence
  passed in run 38322036024 at fd64/tested ed7e5151. The representative diagnostic
  native scan completed once; recovered evidence is retained without a rescan.
- Preserve the separate unapproved next301 testing decision and production
  security/signing/boot requirements. No automatic finding resolution or waiver.

## Current blocker-resolution assessment

- Retained diagnostic evidence evaluated under the approved risk model in
  run38327429782, bound to PR145 policy sourcee599d99f10e6:121blocking pairs,
  421advisory pairs,0KEV,0exceptions. Final source checks passed38327424786; the
  historical severity result is not a new-policy pass.
- Historical first-pass review: eleven of15 old-strict Critical IDs matched
  serious groups; four remained untriaged Critical:
  GO-2026-6604 Windows root escape, GO-2026-6612 HTTP/2 resource accounting, and
  two SSH DoS advisories. The expanded new-policy scope now includes11distinct
  untriaged Critical IDs; complete all-alias/path/platform/impact proof before dispositions.
- Typed dispositions bind exact digest, component, platform and every canonical
  location, positive evidence, reviewer/time and expiry within 30 days. Routine
  cannot waive serious groups; KEV is nonwaivable. Unknown symbols or SELinux
  labels are not blanket mitigations. No disposition is currently active.
- Next 300 source hold and production signing/boot qualification remain separate
  requirements. No new kernel testing approval, merge or publication is granted.
- Resolve verified serious risks through compatible signed owning-package fixes
  or complete artifact proof, while keeping ordinary upstream advisories visible.
  Reuse retained build/scan/recovery and source evidence; no repeated benchmarks.

## Approved upstream policy implementation outcome

- Policy-onlyPR145 targetsmain after externalPR144 merge;212focused tests and
  independent security/integration/parser reviews passed at e599d99f10e6.
- Hosted retained-evidence reevaluation38327429782 completed without rebuild or
  rescan:121blocking pairs(95serious,26untriagedCritical),421advisory,0KEV,0exceptions.
  These are policy dispositions and expanded scope, not package fixes.
- Exactmanifest/policy/native hashes, actual file paths, owners and required
  unblock evidence are in desktop-risk-evaluation/blockers JSON ledgers.
- Next300 sourcehold persists independently; production security/signing/boot
  gates remain unmet. Sourcechecks PASS38327424786; releaseINELIGIBLE.
- Cancelled redundant old-policy main publication38326674435 after same main
  revision passed all four merge-queue builds38324842229; known AnyIO blocker
  remained. No merge or publication performed by this continuation.

## Authenticated consumer continuation — 2026-10-13

PR #147 merged externally at `9d1b0c5b5ebd`; PR #148 now targets main.
The user approved independent channel qualification: generic channels can proceed
as their own security, signing and boot gates clear, while Next retains its hold.

Implemented 27 cmd/go runtime mismatch scopes and 72 independently reviewed
consumer/sumdb scopes, bringing the exact-digest policy to 150 dispositions.
Signed RPM payloads, verified source archives and owning compilation records
prove the named consumer mismatches; these are nonapplicability determinations,
not package fixes or blanket dependency suppressions. New main digests need new
bindings. All 107 focused policy/evidence/selection tests passed.

[Hosted source proof](https://github.com/closure-labs/finite/actions/runs/38354387254)
passed. [Retained policy reevaluation](https://github.com/closure-labs/finite/actions/runs/38356296590)
passed: unchanged observations now yield 71 standard and 119 development
blocking pairs, down from 87 and 135 under the previous reviewed policy.
Owners, unblock evidence and separate verdicts are retained in
[the continuation ledger](../docs/desktop-applicability-continuation-2026-10-13.json).
Compiler/cgo, unresolved network consumers, AnyIO, rclone and the Next source
hold remain explicit. Release eligibility has not been established.

- New main run38353294526 completed all four builds, but generic native scanning
  failed before policy evaluation because the production caller supplied a
  relative SBOM path to the strict evidence collector. Remaining identical
  scans were cancelled as demonstrably doomed. This is a scanner error, not a
  policy blocker; canonical caller-path remediation and three regression tests now pass.
- Temporary read-only validation branch was deleted after successful retained
  reevaluation38356296590; evidence remains in the ledger and hosted artifacts.

## Current implementation and release sequencing

- [x] Final PR148 applicability/scanner head29e8d962 passed all hosted source gates38356992553.
- [x] Sequence standard generic first, development and Next independently; retain all supported threat surfaces.
- [ ] Resolve signed package prerequisites and remaining exact consumer proof; owners and acceptance evidence are in docs/release-implementation-sequence.md.
- [ ] Validate one genuinely changed representative candidate before broadening image work.
- [ ] Prepare exact-digest security, signing, boot, ISO and rollback packet for each cleared channel.
- [ ] Release owner approves concrete qualified publication; no release eligibility exists yet.

- [x] Identify rclone fixed owning build3118644 / FEDORA-2026-e27d24d18c in testing; retain exact publisher evidence.
- [ ] After approved stable promotion, authenticate RPM payload and validate transaction, compiler/modules and auth-proxy compatibility on hosted runners.
- [ ] AnyIO: await signed owning4.14.2 update or verified specific backport; no qualifying Fedora44 build observed.

## Rclone reference and consumer-call follow-up

- [x] Senior developer: add explicit single-package signed reference inspection with unchanged default behavior and bounded inputs.
- [x] Security/QA: independently validate selectors, staged-source status, signature/payload checks and no release claim.
- [x] Hosted evidence: inspect only Fedora's signed rclone1.75.2 candidate; do not enable testing, install or execute package payloads.
- [ ] Security reviewers: resolve specific gRPC and HTTP handler call paths or retain concrete remaining proof gaps.
- Preserve externally initiated PR148 merge-queue validation; follow-up work uses a separate JJ child branch.

- Signed rclone probe38361178024 passed: Fedora44 signature and executable bytes authenticated; actual Go1.26.9, x/crypto0.57.0, x/net0.60.0. Compare official advisory ranges before claiming prospective fixes; no current image clearance.
- PR148 merged externally at4bab5195db5d; its merge-queue source gates passed38360619132.
