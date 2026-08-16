# CI gating and merge queue

`Build Purplefin` has one stable required status, `CI gate`. The gate verifies
that repository checks, input planning, and every selected image build finished
successfully. Dynamic profile jobs may be skipped when no profile input changed;
the gate checks those skips against the planner output instead of treating a
missing matrix job as success.

Pull requests build selected candidates, while every `merge_group` event forces
the complete profile graph. Neither event receives package-write, attestation,
or identity-token permissions. Pushes to `main`, schedules, and manual runs
explicitly dispatched from `main` are the only events allowed to publish. This
keeps a merge-queue candidate from changing GHCR before it merges.

The intended ruleset is checked in at
`ci/github/main-merge-queue.json`. It requires pull requests, resolved review
threads, the GitHub Actions-owned `CI gate`, and a serialized all-green merge
queue. It also prevents branch deletion and non-fast-forward updates.

## Repository prerequisites

GitHub currently limits its native merge queue to organization-owned
repositories. Purplefin is currently a user-owned public repository, so the
checked-in ruleset cannot be activated until the repository is transferred to
an organization with merge-queue access. Keep the ruleset inactive until the
workflow containing `merge_group` and `CI gate` exists on the default branch.

The active personal-repository approximation is checked in at
`ci/github/main-protection.json`. It requires `CI gate`, requires each candidate
to be current with `main`, prevents deletion and force-pushes, and allows
GitHub's ordinary auto-merge to serialize passing pull requests. Unlike a native
queue, it cannot create and validate a temporary group containing multiple pull
requests; a candidate whose base becomes stale must update and pass CI again.

Apply that fallback after the `CI gate` workflow exists on the pull request:

```bash
gh api --method PATCH "repos/${GITHUB_REPOSITORY}" \
  -F allow_auto_merge=true \
  -F delete_branch_on_merge=true
gh api --method POST "repos/${GITHUB_REPOSITORY}/rulesets" \
  --input ci/github/main-protection.json
```

Inspect existing rulesets before posting so the policy is created once rather
than duplicated.

## Native queue upgrade

After that transfer and workflow merge:

1. Enable repository auto-merge.
2. Create an Actions secret named `MERGE_QUEUE_TOKEN`. Use a fine-grained token
   limited to this repository with Contents and Pull requests read/write access,
   or adapt the workflow to mint an installation token from a dedicated GitHub
   App. Add the same value as a Dependabot secret so Dependabot-triggered runs
   can access it. The built-in `GITHUB_TOKEN` cannot add pull requests to a
   merge queue.
3. Apply the ruleset from an authenticated administrative checkout:

   ```bash
   gh api --method PATCH "repos/${GITHUB_REPOSITORY}" \
     -F allow_auto_merge=true
   gh api --method POST "repos/${GITHUB_REPOSITORY}/rulesets" \
     --input ci/github/main-merge-queue.json
   ```

Set `GITHUB_REPOSITORY` to the post-transfer `owner/purplefin` repository before
running the commands. Remove the personal-repository fallback ruleset when the
native queue ruleset is activated so `main` has one authoritative policy.

## Trusted update bots

`Queue trusted update bots` enables auto-merge only for same-repository
Dependabot pull requests and the exact `update_flake_lock_action` pull request.
It checks out and executes no pull-request code and pins the requested head
commit when enabling auto-merge. All normal PR checks must pass before either
update enters the queue, and `CI gate` runs again against the queue's temporary
merge commit.

The flake updater uses `MERGE_QUEUE_TOKEN` when configured so opening or updating
its pull request triggers CI. Without it, the updater falls back to
`GITHUB_TOKEN`; GitHub then requires a maintainer to approve the flake-update
workflow run. For the personal-repository fallback, the built-in token can
enable ordinary auto-merge for trusted updates. A separate token remains
necessary after upgrading to a native queue.
