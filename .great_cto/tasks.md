# Security audit implementation

## Completed upstream preservation and new OS reuse measurements

The owner requested independent hosted inventory and whole-qualification reuse
measurements, then explicitly restored upstream ZFS trust and selected Bluefin's
kernel/modules as one unit. Active variants are now only finite/Bluefin and
finite-dev/Bluefin-DX; Next kernels/variants are retired. Do not dispatch tests,
scans, builds or VM qualifications for retired variants. Keep prior published
releases and historical evidence intact. Preserve Finite's other additions and
upstream configuration as far as their integration permits.

PR #172 merged through the protected queue at 2816fa4d. New main producer 38777997975
passed both upstream-preserving builds, native security, signatures, all four
fresh-install and upgrade/rollback VM phases, desktop acceptance and promotion.
Only these two new OS candidates supplied the reuse benchmarks; no old OS or
retired variant was benchmarked in this comparison.

All four final experiments passed independently authenticated timing checks:
inventory 38787802299/38787811046 and wrapper-inclusive whole-qualification
38793866627/38793870423. PR #173 added scoped SecretSpec credential resolution to
the qualification experiment without changing image or qualification inputs;
its main 38792824985 passed with no new image/VM work. Inventory aggregation uses
the same read-only profile, with unchanged measured inventory-only reader paths.

Inventory median paired savings were 415s/810s; whole-qualification critical-path
service savings were 93.1%/93.6% per exact eligible hit. Production hit rate is not
measured. Reuse defaults remain unchanged, Cachix writing remains false and no
versioned release was created or retagged. All heavy work stayed hosted.
See [upstream foundations](../docs/upstream-kernel-variants.md) and the
[new OS results and next decisions](../docs/new-os-reuse-results.md).

## Completed v0.8 release

User requested continuation of the measured CI plan through v0.8. Scope remains
four existing channels, SecretSpec/devenv credentials, jj and hosted heavy work.
The [v0.8 plan](../docs/v0.8-release-plan.md) supersedes historical release holds
below; their dated evidence remains preserved. Current owner policy accepts VM
qualification and reviewed Critical desktop exploitability, with physical tests
informational. The protected release environment retains its owner review gate.

All four v0.8 channels are now published after explicit owner approval, with
standard Finite latest. All four signatures, signed asset hashes, exact-source
tags and qualification/recovery receipt joins passed; published asset metadata
remains unchanged. The credential blocker below is resolved. See the
[release results](../docs/v0.8-release-results.md) for public links and hashes.

- Implementation: selective batched cache preparation, identity separation and
  qualification mode binding, version/changelog and per-channel release checks.
- Verification: bounded local fixtures plus independent QA/security; hosted
  source/image checks, one genuine v0.8 main generation and all eight VM phases.
- Delivery: preserve four original qualified ISOs, prepare four unsigned packets,
  obtain final ship approval, sign drafts and publish approved channel releases.
- Defaults: automatic writer, inventory/DB and whole-qualification reuse remain
  off until their own measured adoption criteria are met.
- Protected implementation merge: PR165, `aeb59d95`; v0.8 main producer
  38668576342 passed all four profiles and eight VM phases. Small authenticated
  receipts and current registry tag bindings passed. Four release preparations
  capture this frozen source before the follow-up merge. First hosted pilots
  rejected Nix metadata coercion,
  preloaded Docker state and the DB transport bound; preserve those failed
  observations in docs/v0.8-hosted-pilot-results.md. PR166 corrections merged
  through the protected queue after all four release source captures.

## Historical frozen-source release recovery (completed)

All four v0.8 preparations passed original-ISO verification and fresh scanning:
38675610884, 38675636453, 38675653313 and 38675676845. Small authenticated
metadata receipts are retained in the operator audit; no large local downloads.
Standard signing verified successfully, but draft tag creation returned HTTP403
because the default workflow token lacked workflow-write permission for the
frozen source after main advanced. No tag or draft was created. The other three
redundant signers were cancelled after their preparation jobs succeeded.

Implement a reviewed main-only recovery from these exact unsigned packets,
unchanged qualification/policy/tool inputs and owner-protected isolated signing.
SecretSpec separates signing keys from the final exact-source tag/draft publisher.
Preserve original provenance; add signed recovery receipts. Require protected CI
and independent security review before hosted recovery, then verify four drafts
and obtain the final owner publication decision. Do not rebuild images or rerun
VM qualification solely to recover release transport.

## Historical publishing credential blocker (resolved)

PR168 recovery merged at `880ff939`; main CI38680295654 passed. All four
recovery authentication and verified-upload binding jobs passed; standard and
next signing verified, but final tag creation returned HTTP403 `Resource not accessible by personal
access token`. No v0.8 tag or release was created. Await owner update of the
publishing credential to repository contents write plus workflows write; values
must stay out of chat. Original and verified packets remain preserved; the two developer signers were
stopped before redundant denied publishing attempts. Do not
rebuild, retarget, bypass owner review or claim release publication. After the
update, use complete fresh recovery attempts and verify all four signed drafts
before the final publication decision. See the run table in the v0.8 plan.

## Historical October 12 release eligibility sequence (superseded)

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
- [x] HTTP reviewer: retained23 authenticated source files and concrete caller paths; no blanket client-only clearance.
- [x] gRPC security and independent QA: approve six exact Podman/Buildah authorization-only scopes; transport and podman-tui remain blocked.
- Preserve externally initiated PR148 merge-queue validation; follow-up work uses a separate JJ child branch.

- Signed rclone probe38361178024 passed: Fedora44 signature and executable bytes authenticated; actual Go1.26.9, x/crypto0.57.0, x/net0.60.0. Compare official advisory ranges before claiming prospective fixes; no current image clearance.
- PR148 merged externally at4bab5195db5d; its merge-queue source gates passed38360619132.

- [x] Rclone prospective review supports all14 recorded owning pairs in selected candidates; stage compatibility tests before stable adoption. No installed-image findings cleared.
- [x] Cancel redundant main reconciliation38361032151; no further image build/scan requested.

- [x] PR149 merged externally at124049058307; queue38362921128 passed. Cancelled redundant main image run38363454043.
- [x] Apply six reviewed scopes (156 total);69 policy fixtures pass. Hosted reevaluation38364577930 passed with unchanged observations: standard70, development119.
- [x] Validate partial rclone compatibility contracts on hosted isolated runner; preserve missing coverage explicitly.

- [x] PR150 initial head96f984360e6e source checks passed38364965874 (all source gates passed).
- [x] Actual signed rclone run38364908523: ordinary operations, links and both Restic cases passed; FTP timeout is a probe error under investigation, not a vulnerability finding.

- [x] FTP fixture correction: nonempty passive-port range and phase diagnostics;16 offline tests and independent QA pass. Retry38365757103 identified source-confirmed551 response mismatch; corrected with own-file retrieval controls.

- [x] Final actual compatibility38366200031: all five implemented contracts pass;19 offline fixtures pass. Evidence retains both probe errors and remaining coverage gaps.
- [x] Cancel superseded source run38365814706; final code1b4d0cf2 source validation38366217513 passed all gates.
- [ ] Finite: complete SFTP/Windows, RC proxy, S3 identity-secret and mount compatibility before full package adoption.

- [x] Remove temporary audit/rclone-reference branch and forget probe workspace after retaining hosted artifacts and receipts.

## Desktop release qualification implementation

- [x] Senior developer: RC/S3 controls implemented;30 fixtures and hosted7-case run38368702487 pass.
- [x] Security architect: candidate VM receipts bind actual SELinux/process/network observations through qualification, promotion and release.
- [x] Security officer: refresh confirms rclone testing, AnyIO unavailable and Next stable promotion pending; exact owners/events recorded.
- [x] Root: implement qualification contracts and focused tests; retain hosted compatibility/prerequisite evidence in stacked PR151. Hosted source status is tracked on its exact-head checks.
- [x] QA/security: independent RC/S3 and VM source review approved;64 VM/release/resume fixtures pass; actual VM execution remains unproven.
- Preserve PR1505eeee35a and source PASS38366873163; standard generic first; no merge or publication.

- Decision: VM qualification is sufficient; the user explicitly rejected a separate hardware/desktop test gate. Record untested physical/GUI behavior as informational only.

- [x] Retained SBOM prerequisite check38369120537 confirms required guest-tool packages; full SBOM parsed hosted only.
- [ ] Actual candidate VM execution follows a genuinely changed, vulnerability-qualified image; no unchanged-image build/scan or false boot pass.

- CI38369444397 exposed legacy promotion fixtures missing the newly required VM receipt. Fixture boundaries corrected without weakening the production gate;612 broadened offline tests now pass before retry.
- Temporary validation branch removed after retaining run38368702487 and run38369120537 evidence.

## Critical-only desktop release threshold

- Decision: user explicitly narrows vulnerability blocking to Critical findings
  applicable to supported desktop SELinux use; all four profiles and container
  tools remain in scope. Lower-severity risks remain tracked, not falsely fixed.
- [x] Implement exact Critical/alias evaluation and authenticated mode integration (80 policy +51 integration +13 native-summary tests).
- [x] Independently review policy, integration and focused regression tests; approved bounded source scope.
- [x] Reevaluate fresh retained scans from main run38395796884 on hosted runners;
  preserve observations and compare with the retained baseline. No repeated scan.
- [x] Record remaining Critical applicability work: standard24, development54 pairs on both kernel channels; no clearance claimed.
- Actual signed candidate VM qualification remains required; no physical test gate.

- [x] Rebase PR151 after external PR150 merge; cancel redundant four-image run38410619261.
- [x] Hosted removal dry-run38411928635: rclone alone; AnyIO also removes HTTPX; gum/glow have inherited desktop callers. No removal or clearance claimed.
- [ ] Implement compatible optional removal/caller remedies as a batch before the next changed candidate; preserve desktop confirmations and supported container use.

## Evidence-based desktop blocking correction

- Decision: advisory/component pairs alone are insufficient for release blocking.
  Unresolved Critical matches remain advisory review work, not automatic holds.
- [x] Implement explicit reviewed-desktop-exploitability basis and strict exact
  candidate confirmation records; preserve historical policy output.
- [x] Independently assess existing receipts for qualifying confirmed risks and
  validate policy/integration regressions.
- [x] Hosted reevaluation38414548421 reuses fresh native scans; retain all observations,
  distinguish policy acceptance from fixes, update PR and evidence.
- Signing, SELinux-enforcing VM install/upgrade/rollback and evidence validity
  remain qualification gates. No merge/publication is part of this correction.

- Independent review: no qualifying confirmed risk in existing current-candidate receipts; unresolved risks explicitly accepted, not resolved.157 policy/integration regression tests pass.

- All four candidates pass revised vulnerability policy with zero confirmed blockers. Unresolved Critical observations retained: standard24/development54, advisory only. Proceed to trusted signing/VM qualification after the reviewed source change reaches main; no required vulnerability-count reduction.

## Signing compatibility and independent candidate resume

- [x] Diagnose run38426200092: all four builds/security passes; legacy Cosign flags conflict with signing-config default.
- [x] Pin signer to reviewed Cosign3.1.3 and explicitly select compatible legacy signing; preserve transparency verification and isolated secrets.
- [x] Hosted smoke38432226349: ephemeral-key sign/verify passed, wrong key rejected, real transparency verified; no production key used.
- [x] Implement authenticated native security-evidence reuse with current policy/freshness reevaluation and retained original timestamps; 12 helper,90 policy,20 resume,16 selection tests pass.
- [x] Independent security/CI review approved; helper source loading avoids introducing bytecode into image identity.
- [x] Hosted source38434206098 and merge-queue38435138430 passed; PR #152 merged at31cdca7ffc15.
- [x] Attempt trusted standard resume38435953230; rejected current-input identity mismatch before signing. Preserve failed evidence; do not bypass guard.
- Next resume is superseded by the fresh deterministic-identity build sequence below; do not repeat the same mismatch.
- No additional vulnerability-count reduction or physical hardware test is required by current policy. Outstanding release gates are operational evidence, not advisory-pair counts.

## Deterministic image input identity

- [x] Exclude only generated tooling .pyc/.pyo from identity; authored/shipped inputs remain bound.120 focused tests and independent review pass.
- [x] PR #153 merged atb274129fc76f after source38437866524 and queue38438814330 passed. Defer the build-only disk cleanup optimization to a later image-workflow change so this tooling PR does not trigger four unnecessary validation builds.
- [ ] Build one fresh standard candidate under corrected identity; scan, sign and VM qualify before promotion.
- [ ] Build and qualify Next independently; do not retry old mismatched identities.
- This is a release tooling/provenance correction, not a vulnerability-policy failure or additional security exception.

- Fresh standard run38439778084 has passed source checks and entered image build atb274129fc76f. Next remains sequenced after standard evidence; no release eligibility claimed.

## Doppler OIDC assessment and fresh-candidate signing diagnosis

- [x] Review official action source, OIDC claims, live repository settings and protected-environment metadata; independent security/integration review supports a canary-only pilot.
- [x] Diagnose38439778084: build and security pass; signer receives empty COSIGN_PRIVATE_KEY because the reusable caller does not forward the secret. No stored-key corruption established.
- [x] Implement explicit named secret forwarding and a bounded public-key preflight; 151 focused signing/selection/resume/pilot tests pass. Hosted validation and exact-digest signing passed; upgrade VM qualification remains incomplete.
- [x] Resume exact digest60b12153f6c3 without rebuilding:38455754348 reused valid security evidence and signed it, then exposed the VM matcher defect. Superseded by repaired, fully qualified fresh candidate38467981855.
- Doppler adoption is optional and requires verified subscription/workspace configuration and positive/negative canary tests; no integration or secret migration performed by this assessment.
- Assessment and rollout constraints: docs/doppler-oidc-assessment-2026-10-13.md.

## Authorized Doppler canary rollout

- [x] User authorized implementation and rollout; separate this pilot from release qualification.
- [x] Create empty `doppler-pilot` environment, restrict to main, disable administrator bypass; existing signer/release protections unchanged.
- [x] Deploy manual claims-only/canary workflow. Run38452109711 passed exact public claims in5s; no Doppler fetch or backend denial test attempted without a workspace.
- [ ] Verify positive/negative Doppler authentication before trialing the read-only audit App.
- External blocker: user confirms no Doppler workspace exists. Owner: organization administrator; unblock by creating an entitled Team/Enterprise workspace, a canary-only config and narrowly constrained service account/identity. No production secret migration until pilot evidence passes.
- [x] Pilot behavioral fixtures verify claim matching, HTTP401/403 denial, unexpected success, malformed/rate-limit/server/network failures and token non-disclosure; workflow lint and documentation checks pass.
- [x] Hosted38448894056 caught missing action allowlist entry. Add only the reviewed Doppler SHA and main-only pilot environment to tracked/live security policy; delivery and full repository-policy fixtures pass.
- [x] Hosted38449803661 exposed a stale blanket no-secret-forwarding assertion. Require exactly the named signing key and retain nested-job isolation; 215 broadened focused tests pass before retry.
- [x] PR #154 merged at31e47a59f456 after source38450595473 and queue38451388697 passed. Redundant automatic build38452072161 cancelled; exact standard candidate resumed in38452104611 and claims-only pilot38452109711 launched.
- [x] Repair sandboxed Skopeo credential lookup exposed by resume38452104611; source/candidate recovery passed, but default /run/containers/1001/auth.json is unreadable. Signing was not attempted in that failed run; corrected resume38455754348 reused the same digest and passed signing.
- [x] Implement scoped registry-auth repair with153focusedtests and workflow lint passing; helper preserves all current trust/resource gates and candidate identity. Hosted rollout passed in38455754348.
- [x] PR #155 merged at3fd275c98d98 after source38454295599 and queue38454956311 passed; independent registry-auth review approved. Cancelled redundant38455635843 and resumed same candidate in38455754348.
- [x] Live corrected reuse38455754348 passed: original native evidence revalidated under current policy and original timestamps, no new scan. Protected signing passed key-match, signature and transparency verification; fresh Secure Boot/encrypted-root/enforcing VM passed; upgrade stopped at the wrong-key rejection probe, whose error log was discarded. No promotion.

- [x] Diagnose wrong-key bootc rejection and retain fresh VM diagnostics. The historical38455754348 error was deleted, but38467981855 captured the exact missing-signature rejection and passed signed upgrade/rollback after the matcher repair; generic bootc errors remain failures.

- [x] Implement the explicit missing-signature rejection match and private/sanitized VM diagnostic retention;32focusedVM/desktop/resumetests and shellcheck/docs pass. Hosted source/queue and fresh standard candidate38467981855 subsequently passed; the harness identity was preserved.

- [x] PR #156 source38466401141 passed at21bde0368b1e; independent VM security review approved. Merge queue38467226440 passed; PR #156 merged at85a37e0c1b88. Diagnostic38466268480 observed correct-key OpenImage acceptance and explicit wrong-key missing-signature rejection but failed at wrapper shutdown; preserve overall failure. Temporary diagnostic branch deleted; no extra probe needed to support the matcher repair.

- [x] Complete fresh standard rollout38467981855 at85a37e0c1b88 with repaired VM rejection matching and diagnostics. Redundant automatic run38467897021 cancelled; all security/signing/boot gates remain enforced.

- [x] Standard rollout38467981855 passed all gates: fresh candidate3b3e867d6869, reviewed Critical desktop policy with zero blockers, protected signing, Secure Boot/encrypted-root/enforcing VM fresh install/signed upgrade/rollback, promotion and CI. Independent VM receipt validation and public finite/latest digest reads passed. Next/development qualification remains independent; Doppler backend pilot awaits owner workspace.

## VM upgrade transfer supervision (2026-10-13)

- [x] Inspect cancelled development-Next qualification115616213450: fresh installation passed; signed upgrade emitted no progress for24m34s before cancellation. Upgrade diagnostics were not retained, so root cause remains unknown.
- [x] Add a30-minute host/guest upgrade deadline, minute-by-minute resource/I/O probes and sanitized incremental checkpoints that survive interrupted final cleanup. Focused timeout, failure, cancellation and redaction tests pass.
- [ ] Run the improved upgrade harness against candidate3da12596aef2 and predecessor33e7b69d9c59 alongside original retry115641293003. Diagnostic evidence does not replace production qualification or promote channels.


## Promotion revision race (2026-10-13)

- [x] Confirm production retry38486865970/2 passed development-Next qualification but promotion rejected a newer main revision after harness PR159 merged.
- [x] Preserve exact qualification across proven documentation-only descendant revisions; retain rejection of changed release inputs, incomplete comparisons and channel drift. Add focused regression coverage.
- [ ] Finish current-main publication38503750779 before merging the promotion fix; its unchanged workflow would otherwise reject another main advance. The prior failed run is retained as evidence, not bypassed.


## Determinate workflow resource audit (2026-10-14)

- [x] Audit all host Nix jobs and qualification guests; all host Nix callers already install the pinned Determinate action. Replace hard-coded concurrency with CPU/RAM/cgroup-aware budgets and verify effective settings without revealing configuration secrets.
- [x] Enable measured parallel evaluation; preserve bounded per-builder CPU use, cache behavior, lightweight maintenance entry points and benchmark cache isolation. Size guest commands from the2-CPU/4-GiB VM rather than host hardware.
- [ ] Validate the exact change on hosted runners, including actual installer settings and focused contracts. Keep publication gates and merge sequencing intact.
