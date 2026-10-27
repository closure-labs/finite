# Release safety and remaining CI work, October 27 UTC

This audit reviews source `41b5ad889713769ab449fd1158c3e5692e0fcfab`, including
the pending #287 scanner change. It maps existing safeguards to production
callers and offline regressions rather than adding duplicate authority gates.
The [machine-readable evidence](ci-release-safety-audit-2026-10-27.json) retains
source hashes, 320 passing tests across 18 suites, bounded live metadata and a
workflow inventory of credential references, App permissions and artifact
retention. Secret values were neither requested nor recorded.

The release is **not yet qualified**. Source coverage, native observations and
final candidate acceptance are separate evidence. The
[completion ledger](v0.8.3-release-plan.md) remains the current work list.

## Admission and recovery: A2

| Boundary | Implementation and regression evidence | Remaining observation |
| --- | --- | --- |
| Trusted execution approval | `ci-run-admission.py` authenticates the open PR's full repository/branch/head tuple and live Decider or Super Admin author; its 29 tests cover moved heads, revoked membership, incomplete origins and unsupported execution states. | A natural external-contributor execution hold has not been repaired in the retained Finite evidence. |
| Approval versus execution | The admission worker only calls Actions `/approve`; authority checks independently evaluate current human review. It cannot approve a review, publish a successful check or approve an environment. | An execution hold and a rejected authority status must remain separately diagnosed. |
| Delayed review and missed authority events | `decision-check.py` has 42 tests covering delayed approval, stale snapshots, periodic/manual recovery, queue movement and review changes during validation. `decision-authority.py` has 55 tests covering immutable identity, live eligibility and merged bytes. | #286's rejected authority status recovered 88 seconds after review; CI was already running. No scheduler latency guarantee follows. |
| Coalesced execution events | Each serialized admission worker reconciles the complete current blocked set; uncertain POST responses are read back without blindly repeating the mutation. | Event delivery outages still require native observation or operator recovery. |

The implementation audit found no missing approval check requiring another
gate. Authority recovery has event, periodic and targeted manual entry points.
Execution admission has PR lifecycle and blocked-completion entry points; it
does not have the authority workflow's periodic schedule. Do not describe those
as one universal scheduled execution restart. Keep natural execution-hold
observation open; do not manufacture a fork or VM round for evidence.

## Paired release safety: A3

| Invariant | Production path | Focused evidence |
| --- | --- | --- |
| Immutable products and original producer | `execute-release-set.py` authenticates the trusted packet, original Actions ZIP and approved inventory; `release_handoff.py` binds native preparation and signing attempts. | Release-origin, preparation, handoff and execution fixtures reject forged origins, changed hashes, unsafe ZIP members and failed producers. |
| Live human approval and security | `approved()` checks the current merged proposal; prepare rescans both images; signing checks precede keys; publication guards repeat at each channel boundary. | Authority, revocation, publication-authority and execution fixtures cover dismissal, changed payloads, stale evidence and revoked approval. |
| Credential renewal without duplicate transport | Stage uses the job's artifact-read token; renewed App authority reauthenticates staged bytes. Publication stages assets, renews authority again, then commits. | Execution fixtures cover transfers outliving authority credentials, staged-byte alteration, token restoration on failure and revocation after staging. |
| Reservation and executor exclusion | `release_set.py` reserves `versions/VERSION.json` on `automation/release-journal`, uses CAS journal writes and a bounded executor lease. | Release-set fixtures cover competing payloads, concurrent executors and CAS conflicts. |
| Interrupted uploads and lost responses | The adapter reconciles remote tags, draft identity, asset hashes and bounded empty placeholders before retrying a write. | Release-set fixtures cover lost successful responses, partial uploads, changed placeholders and preservation of conflicting or published assets. |
| Partial publication | Both inventories are staged before publication; current authority is checked again for each channel. Matching published products are preserved on recovery. | Release-set fixtures cover revocation after the first publication and completing the remaining channel without replacement. |

The source audit found these guards already implemented. No production failure
was manufactured and no frozen execution, reservation, decision or asset was
modified. Operating instructions now explicitly state that the exact proposal
review is the human approval; the main-only signing environment scopes keys and
adds no second manual reviewer. Live environment metadata agrees: one `main`
branch policy and no required-reviewer rule.

At the snapshot, neither stable `finite-0.8.3` nor `finite-dev-0.8.3` existed.
Both published development tags remain present. The actual journal branch
exists and its stable `versions/0.8.3.json` reservation returned 404. These are
point-in-time observations, not a reservation or authorization to publish;
repeat the checks before freeze. Current-source qualification, fresh security,
workstation acceptance and the paired release proposal remain R1 requirements.

## Credentials, cache trust and artifacts: A4

The maintained paired publisher keeps its write PAT separate from the read-only
authority App token. The operator chose to retain that PAT. Decider cannot
currently issue a token with Workflows write: the explicit capability request
returned HTTP 422. No App permissions were expanded. Replacing the PAT without
that capability would break historical-source tagging.

`MERGE_QUEUE_PAT` was absent from the complete repository and `release`
environment secret-name inventories. The organization grant endpoint returned
403. This does **not** prove the credential is missing: organization delivery,
effective permissions and expiry remain unknown. Secret update timestamps are
not expiry evidence. Before stable publication, the credential owner must verify
Finite access, Contents/Workflows write, expiry and rotation ownership without
disclosing the value.

The static workflow inventory also identifies updater consumers and retired
single-channel release consumers. Retired paths remain fail-closed compatibility
boundaries, not candidates for an unreviewed credential migration. Authority
tokens are repository-scoped; signing keys are isolated from preparation and
publication. Existing regressions enforce these boundaries.

Artifact retention follows separate lifetimes:

- Source-check proofs and ordinary image build evidence retain 14-day windows;
  missing or expired eligible proofs fall back to full validated work.
- Production phase evidence retains seven days; aggregate qualification and
  publication-preserved ISO evidence retain 90 days. Preserve exact aggregate
  provenance when older phase artifacts expire.
- Paired proposals, native publisher identity, signing handoffs and signed
  execution evidence retain 90 days. Immutable product and signed OCI references
  remain necessary for durable recovery beyond transient Actions artifacts.
- Small diagnostics use bounded retention; qualification preparation scratch
  evidence uses one day. Neither substitutes for accepted production evidence.

Cache restores are hints, not approval evidence. The shared setup permits checks
snapshot writes only from trusted main checks contexts; PR/queue jobs cannot
write that lane. Source snapshots have their own trusted-main conditions.
Derivation identities, validated proof outputs and origin checks remain required.
Automatic Cachix writing and Grype database transport stay disabled. This audit
does not certify organization-wide cache configuration or OCI garbage-collection
policy; retention ownership must be checked before deleting recovery inputs.

## Performance dispositions and next implementation

The [159-run census](ci-recent-census-2026-10-27.md) remains the conserved recent
baseline. Installer/VM work consumed 23,003 of 36,246 runner seconds. Stage times
overlap native job cost, and exact cross-workflow dependency contribution remains
unknown. Do not add nested timings to native totals or equate runner occupancy
with workflow latency.

| Finding | Current disposition | Next concrete work / exit |
| --- | --- | --- |
| #285 production preflight / #286 predecessor diagnostics | Awaiting natural production execution | Authenticate the next upgrade phase receipt and classify counters before changing reuse keys or fallback. No-image mains cannot exercise these paths. |
| O1 / M1 source and dependency costs | Recent census completed; attribution remains open | Join bounded stage receipts with native job dependency/queue timing; keep unresolved cross-workflow edges and receipt gaps unknown. Preserve exact unique-execution accounting. |
| O2 controller parallel reads | Current campaign closed inconclusive; serial retained | The deadline elapsed with zero native canary samples. Serial-default variable absence was restored at 02:19:02 UTC and rechecked. A new experiment needs a fresh preregistration and matched native control; replay is not adoption evidence. |
| O3 installer runtime reuse | Technically blocked pending a safe boundary | Candidate-specific upgrade configuration is injected before runtime compression. Map a late-injection or pre-template boundary and the complete signed RPM/repository/template/certificate/tool closure before proposing reuse. |
| O4 Foundation initializer | Next instrumentation target | Measure evaluation/fetch/realization, Homebrew, Flatpak readiness and activation within pinned Foundation. Publish reviewed instrumentation before updating Finite. Preserve inherited resource settings and exactly one initialization. |
| O5 compression | Deferred until matching cohorts are attainable | Verify released runner/runtime/cache cohort feasibility cheaply before any full comparison. Retain production default and earlier failed samples. |
| O6 release transport | Rejected prototype remains deferred | Keep original-ZIP verification. Reopen only for a materially different measured design. |

Existing Foundation resource limits are not evidence that raising them is safe
or beneficial. Installer and guest changes still require both profiles' fresh
and upgrade/rollback acceptance plus the existing matched warm/cold gates.
Retained local OCI verification remains deferred until an exact same-build
export exists; registry-only diagnostics cannot resolve that boundary.

## Verification limits

The protected #287 queue attempt
[40441743136](https://github.com/closure-labs/finite/actions/runs/40441743136)
failed while fetching NARs from `cache.nixos.org`. Curl reported interrupted
sends/receives, followed by HTTP 416 on a resumed transfer. The aggregate
derivation matched the successful PR aggregate. No contract assertion was the
reported cause. A single normal protected-queue retry was requested at the
unchanged approved head; it remains separate from the failed attempt's cost.

The follow-up narrowly recognizes those explicit curl transport messages in
the existing three-attempt wrapper. HTTP 416 alone remains nonretryable. Build,
evaluation, permission, integrity, signal, disk-full and quota failures override
transient warnings. Retrying builds the already evaluated aggregate and does
not repeat successful evaluation. The 41 wrapper regressions passed, including
both observed curl variants and terminal-failure precedence. Hosted pinned
aggregate validation remains required for this executable change.

All 320 safety regressions and 41 wrapper regressions passed using installed
Python/static tools. The
first release-recovery suite attempt hit the local scratch quota in its oversized
metadata fixture; after removal of a verified-clean superseded checkout, all 24
tests in that suite passed unchanged. The JSON retains both outcomes.
No local Nix evaluation/build, VM, workflow dispatch or production mutation was
used for the audit. Documentation checks cover the resulting report and corrected
operating instructions. Native observations and final-source release checks
remain explicitly open rather than being inferred from fixtures.
