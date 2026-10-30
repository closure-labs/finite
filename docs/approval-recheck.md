# Recheck a pull-request approval

Approvals have no ten-minute expiry. Cached authority observations do: the
periodic controller revalidates observations aged ten minutes or more so an
unchanged review cannot indefinitely hide team or permission loss. This is a
scheduled backstop, not instantaneous revocation; execution admission and new
queue authority checks still re-read current eligibility. A review must cover the exact current PR
head and come from a currently eligible Super Admin. Pushing a new head still
requires a new review. Dismissals, withdrawal comments, changes requested and
lost eligibility retain their existing effect.

A PR review normally triggers the event collector and a fresh maintainer
authority check. An older failed Actions run remains historical. Look at the
current required **Maintainer decision authority** result and its linked
verification run to see whether the latest review has been validated.

## Recheck now

In Actions, open **Verify maintainer decision authority**, select **Run workflow**,
choose `main`, and enter the PR number. From the CLI:

```bash
gh workflow run decision-authority.yml --repo closure-labs/finite --ref main -f pull_request=273
```

The action reads the current open PR head and any current protected queue
reference, then repeats the existing live approval and governed-content checks.
It can update a stale authority result after a delayed approval or missed event.
It cannot approve the PR on your behalf, waive a missing review, admit an
unsupported author, replace the queue, rerun source/VM tests or publish anything.
The workflow accepts recovery only from its own native main-branch execution.
Selecting another branch cannot start the credentialed worker.

This action is separate from GitHub's **Approve and run** execution hold.
[Trusted CI admission](ci-execution-admission.md) handles those holds for Decider
and live Super Admin authors. Real test failures still need diagnosis and an
intentional retry after correction.

## Automatic recovery

A periodic metadata probe runs at minutes 7, 22, 37 and 52. It reads bounded
native open-PR, review, current queue-reference and App-origin check inventories.
Only missing or stale review checks become worker targets. Discovery needs no
Nix setup or App credentials; unchanged checks produce an empty matrix and no
credentialed worker.

Each authority result records a digest of the relevant native review snapshot
and the exact PR head. That digest is an observation, not an approval. A changed
approval, dismissal, changes request or explicit self-review command makes the
snapshot stale. Irrelevant comment reviews do not. Stable success and stable
review rejection require no repeated Nix/App work. Legacy unstamped results get
one normal revalidation. A transient GitHub metadata failure is marked for a
later retry, with a two-minute grace period for ordinary event workers.

The writer always reruns live authorization. It rechecks the head and queue
reference before posting, and discards a result if reviews change during
validation. Workers retain per-PR/target serialization without cancelling an
active writer. A scheduled or manual invocation cannot manufacture a successful
review from a digest, workflow input, old result or event payload. App scopes,
human review requirements and independent publication checks are unchanged.

The schedule is recovery, not an immediate delivery guarantee: GitHub may delay
scheduled jobs or have API/runner outages. Use the manual action when a fresh
check is needed now. It also revalidates current team eligibility even when the
review snapshot has not changed. Native workflows and fresh security/publication
checks retain their separate failure outcomes.

## Validation and rollout

Focused fixtures cover an approval after a 30-minute rejection, approvals with
old timestamps, stable missing approval, manual forcing, dismissal/withdrawal,
head movement, queue replacement, mismatched App checks, incomplete metadata,
transient failures and reviews changing mid-validation. A recovery invocation
only posts the authority check; it never dispatches or reruns image, test or
publication workflows.

The preceding [CI-admission rollout](https://github.com/closure-labs/finite/pull/273)
merged at `3b709161b4439ddeb06c5291107869052fb9ddf9`. Its protected queue used
475 runner seconds and main used 425; both passed without image jobs. Natural
reconciliation and delivery health passed. Main's authenticated source lookup
took 2.272 seconds and produced the second natural shadow match. Keep source
proof in shadow at two of five required comparisons; these observations are
not a savings benchmark. No local Nix evaluation/build or VM run was used.
