# CI gating and merge queue

`Build Purplefin` has one stable required status, `CI gate`. The gate verifies
repository checks and every planning, image, and installer job selected by the
change classifiers. Documentation-only changes complete through the repository
checks, while image and installer changes add their corresponding build jobs.
The gate matches every skipped job to planner and classifier output.

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

## Active repository policy

The active `Protect main with CI gate` ruleset comes from
`ci/github/main-protection.json`. It requires pull requests, resolved review
threads, the GitHub Actions-owned `CI gate`, and a candidate current with
`main`. It also protects `main` from deletion and non-fast-forward updates.
Repository auto-merge serializes passing pull requests, and merged branches are
deleted automatically.

Apply the checked-in policy to another user-owned repository after its `CI
gate` workflow is present on the default branch:

```bash
gh api --method PATCH "repos/${GITHUB_REPOSITORY}" \
  -F allow_auto_merge=true \
  -F delete_branch_on_merge=true
gh api --method POST "repos/${GITHUB_REPOSITORY}/rulesets" \
  --input ci/github/main-protection.json
```

Inspect the repository's existing rulesets before creating the policy.

## Activate the native merge queue

GitHub's native merge queue is available when an organization owns the
repository. The workflow already handles `merge_group` candidates, and
`ci/github/main-merge-queue.json` contains the queue ruleset.

After transferring the repository:

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

Set `GITHUB_REPOSITORY` to the organization-owned `owner/purplefin` repository
before running the commands. Keep one active `main` ruleset by retiring the
user-owned policy as the native queue policy is activated.

## Trusted update bots

Dependabot groups and updates GitHub Actions. `Queue Dependabot updates` runs
daily on the default branch, verifies open pull
requests through the GitHub API, and enables auto-merge only for non-draft,
same-repository Dependabot updates targeting the default branch. It pins the
requested head commit and operates exclusively on GitHub API metadata. The
scheduled workflow has permission to enable auto-merge while Dependabot
pull-request workflows retain their read-only token.
Branch protection still requires the candidate to be current and pass `CI gate`
before GitHub can merge it.

`Update Nix flake inputs` uses Determinate Nix and the pinned Determinate lock
updater once a week. It refreshes every input in `flake.lock` on the fixed
`automation/weekly-flake-input-refresh` branch, then uses the shared validator
to verify the expected author, title, base, same-repository branch, and exact
head commit before enabling auto-merge. Set `AUTOMATION_UPDATE_LOGIN` when
`MERGE_QUEUE_TOKEN` creates pull requests as a user or GitHub App other than
`github-actions[bot]`.

The Image Builder updater validates and merges its own exact pull request. When
`MERGE_QUEUE_TOKEN` causes the normal pull-request workflow to run, the shared
validator reuses and waits for that run. With `GITHUB_TOKEN`, it dispatches
`Build Purplefin` in validation-only mode. Validation-only dispatches use
read-only package permissions. A separate token provides native-queue enqueue
permission after an organization transfer.

The Image Builder updater follows OSBuild's scheduled pinned-CI-image refresh
pattern. It resolves the mutable `image-builder-cli:latest` discovery tag, then
changes only the immutable digest in the shared installer build action. The
change classifier selects that generic-installer build during pull-request or
validation-only CI, and the stable gate requires its QEMU smoke boot before
auto-merge. The resulting immutable digest constructs each release artifact.
