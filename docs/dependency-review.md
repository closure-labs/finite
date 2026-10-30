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
