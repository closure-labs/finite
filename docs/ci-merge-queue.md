# CI gating and merge queue

`Build Purplefin` has one stable required status, `CI gate`. The gate verifies
that repository checks, input planning, and every selected image build finished
successfully. Dynamic profile jobs may be skipped when no profile input changed;
the gate checks those skips against the planner output instead of treating a
missing matrix job as success.

Pull requests and `merge_group` events build the profiles selected by immutable
input, base-digest, and parent-digest comparisons. A selected parent brings its
descendants into the candidate graph. Neither event receives package-write,
attestation, or identity-token permissions. Pushes to `main`, schedules, and manual runs
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

`Queue Dependabot updates` runs daily on the default branch, verifies open pull
requests through the GitHub API, and enables auto-merge only for non-draft,
same-repository Dependabot updates targeting the default branch. It pins the
requested head commit and operates exclusively on GitHub API metadata. The
scheduled workflow has permission to enable auto-merge while Dependabot
pull-request workflows retain their read-only token.
Branch protection still requires the candidate to be current and pass `CI gate`
before GitHub can merge it.

The flake and Image Builder updaters validate and merge their own exact pull
requests. The Dependabot workflow is scoped exclusively to Dependabot. When
`MERGE_QUEUE_TOKEN` causes the normal pull-request workflow to run, the shared
validator reuses and waits for that run. With `GITHUB_TOKEN`, it dispatches
`Build Purplefin` in validation-only mode. Validation-only dispatches use
read-only package permissions. A separate token provides native-queue enqueue
permission after an organization transfer.

The Image Builder updater follows OSBuild's scheduled pinned-CI-image refresh
pattern. It resolves the mutable `image-builder-cli:latest` discovery tag, then
changes only the immutable digest in `build-installer.yml`. Before auto-merge it
uses the same validation-only CI dispatch and also builds and smoke-boots the
generic installer from the candidate branch. The discovery tag is never used
to construct a release artifact directly.
