# Review native dependency updates

Dependabot remains the PR author. The dependency exception authenticates its
native bot identity (`dependabot[bot]`, user ID `49699333`) and both repository
IDs before considering a same-repository, open PR targeting `main`. Labels,
titles, comments and self-reported dependency metadata never grant authority.

The initial supported family is existing GitHub Actions pins in workflow and
composite-action files, including existing reusable-workflow references. Every
changed file must already exist as a regular `100644` blob. Complete immutable
merge-base/head trees and hash-verified bytes must agree with the complete
native PR inventory. Nothing is inferred from a potentially truncated patch.

The trusted worker parses actual `uses` nodes and permits only a full 40-hex
commit change for the same action owner, repository and subpath, plus its
adjacent `# vN`, `# vN.N` or `# vN.N.N` comment. It verifies the new commit against
that exact upstream tag, including bounded annotated-tag dereferencing. A SHA
merely visible through a repository's commit endpoint is insufficient.
Everything outside those spans must remain byte-identical. New actions,
permissions, events, scripts, inputs, environment changes, renames, file modes,
duplicate YAML keys, aliases, tags and multiline lookalikes are rejected.

Unsupported forms or moved/missing upstream tags remain blocked with a precise
diagnostic; there is no bot exemption or automatic reauthoring. Correct the
same PR where possible and review its new head. Lock files are not included:
FINite's paired `flake.lock`/`devenv.lock` and qualified Foundation input need
their own typed source/provenance contract before native Nix ownership changes.

## An action bump is one PR

GitHub's allowed-actions setting names repositories, not commits. Each
third-party action has one `owner/repo@*` pattern in
`actions.selected_actions.patterns_allowed` of
[`automation/github/repository-security.json`](../automation/github/repository-security.json).
A Dependabot bump of an already-allowed action therefore starts its workflows
without a second PR or a settings edit. Dependabot opens two grouped PRs,
`github-owned` (`actions/*`, `github/*`) and `third-party` (everything else).

The exact commit is still enforced, by three independent controls:

- GitHub's `sha_pinning_required` setting and `tests/ci/delivery-policy.py`
  require every `uses:` reference to be a full 40-hex commit.
- The trusted worker verifies each new commit against the upstream published
  tag, as described above.
- A Super Admin approves the exact PR head.

Verified-publisher actions stay disallowed (`verified_allowed: false`).

An administrator must keep the live setting (Settings → Actions → General →
"Allow closure-labs, and select non-closure-labs, actions and reusable
workflows") equal to the patterns in that JSON file. The repository security
audit reports any difference as drift on
`actions.selected_actions.patterns_allowed`. Adopting a new action is the only
change that needs a pattern: add it to the JSON file and both
`tests/fixtures/repository-security` snapshots in the PR that introduces the
action, then add it to the live setting.

## Never use "Update branch" on a Dependabot PR

"Update branch" adds a merge commit authored by the person who clicked it. The
PR is then no longer Dependabot-only, so the dependency exception stops
applying, and Dependabot refuses `@dependabot rebase` because the branch has
foreign commits. The `main` ruleset does not require branches to be up to date
(it is non-strict) and the merge queue tests the merged result, so updating the
branch is never needed. If a Dependabot PR is stale or conflicted, comment
`@dependabot rebase`; if someone already pushed to it, comment
`@dependabot recreate`.

## Human merge approval remains mandatory

The existing App authority check requires an active human member of the pinned
`closure-labs/super-admins` team with maintain/admin access to approve the exact
current head. A push, dismissed/withdrawn approval, unresolved eligible changes
request or lost eligibility blocks authority. The dependency exception does
not change who may submit release or security proposals, and cannot publish a
product. Merge-queue governed content must still match the approved PR head.

The ordinary PR preflight uses standard-library metadata/tree checks only. It
does not grant approval or claim semantic pin validation. The trusted-main App
merge-authority worker performs the strict parser and live review checks.
Execution admission independently performs the same strict pin classification
and live bot/repository/head revalidation without requiring human review. It
resolves a pinned Python/PyYAML tool before App credentials and never loads PR
code with those credentials. Only precisely bound native Actions executions
are approved. PR readiness is unchanged; protected merge review remains
mandatory. The admitted PR jobs receive no secrets or write permissions.

A successful review collector wakes discovery for older blocked runs. Completed
trusted-main authority workflows provide bounded recovery if that event was
missed; they do not dispatch replacement CI or grant approval themselves. A
successful workflow is only a signal to reconcile, never approval evidence.
Cached App results also do not prove perpetual eligibility: scheduled authority
reconciliation refreshes observations aged ten minutes or more. The review
itself does not expire; current-head review and current eligibility are checked
again rather than asking a still-eligible human to repeat an unchanged review.

See [trusted CI admission](ci-execution-admission.md),
[approval recheck](approval-recheck.md) and
[GitHub's Dependabot execution restrictions](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions).
