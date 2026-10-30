{pkgs}: rec {
  trustedUpdate = pkgs.writeShellApplication {
    name = "finite-trusted-update";
    runtimeInputs = with pkgs; [bash coreutils gh jq];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      : "''${GH_TOKEN:?GH_TOKEN must be set}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY must be set}"
      : "''${PR_NUMBER:?PR_NUMBER must be set}"
      : "''${EXPECTED_BRANCH:?EXPECTED_BRANCH must be set}"
      : "''${EXPECTED_TITLE:?EXPECTED_TITLE must be set}"
      : "''${EXPECTED_AUTHOR:?EXPECTED_AUTHOR must be set}"
      : "''${DEFAULT_BRANCH:?DEFAULT_BRANCH must be set}"
      [[ $GITHUB_REPOSITORY =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]
      [[ $PR_NUMBER =~ ^[1-9][0-9]*$ ]]

      read_pr() {
        timeout 60s gh pr view "$PR_NUMBER" \
          --repo "$GITHUB_REPOSITORY" \
          --json number,author,baseRefName,changedFiles,files,headRefName,headRefOid,headRepository,mergeStateStatus,state,title
      }

      validate_pr() {
        local candidate=$1
        [[ "$(jq -er '.number' <<<"$candidate")" == "$PR_NUMBER" ]]
        [[ "$(jq -er '.state' <<<"$candidate")" == OPEN ]]
        [[ "$(jq -er '.title' <<<"$candidate")" == "$EXPECTED_TITLE" ]]
        [[ "$(jq -er '.author.login' <<<"$candidate")" == "$EXPECTED_AUTHOR" ]]
        [[ "$(jq -er '.baseRefName' <<<"$candidate")" == "$DEFAULT_BRANCH" ]]
        [[ "$(jq -er '.headRepository.nameWithOwner' <<<"$candidate")" == "$GITHUB_REPOSITORY" ]]
        [[ "$(jq -er '.headRefName' <<<"$candidate")" == "$EXPECTED_BRANCH" ]]
        [[ "$(jq -er '.headRefOid' <<<"$candidate")" =~ ^[0-9a-f]{40}$ ]]
        if [[ -n "''${EXPECTED_FILES:-}" ]]; then
          jq -e --arg allowed "$EXPECTED_FILES" '
            ($allowed | split(",")) as $allowed_files |
            (.files | type == "array" and length > 0) and
            (.changedFiles | type == "number" and . == floor) and
            (.files | length) == .changedFiles and
            ([.files[].path] | unique | length) == .changedFiles and
            all(.files[]; (.path as $path | $allowed_files | index($path)) != null)
          ' <<<"$candidate" >/dev/null || {
            echo 'Pull request changes files outside the declared automation scope or has an incomplete file inventory' >&2
            return 1
          }
        fi
      }

      pr="$(read_pr)"
      validate_pr "$pr"
      head_sha="$(jq -er '.headRefOid' <<<"$pr")"
      pr_url="https://github.com/$GITHUB_REPOSITORY/pull/$PR_NUMBER"

      # Native checks, human authority and the protected merge queue own the
      # wait. Never change the head, approve a run or dispatch replacement CI.
      latest="$(read_pr)"
      validate_pr "$latest"
      [[ "$(jq -er '.headRefOid' <<<"$latest")" == "$head_sha" ]] || {
        echo 'Pull request head changed before native continuation; no request made' >&2
        exit 1
      }
      if [[ "$(jq -er '.mergeStateStatus' <<<"$latest")" == BEHIND ]]; then
        echo "Pull request is behind its base; preserving $head_sha and native requirements."
        echo 'Any deliberate branch update needs review of its new head.'
      fi
      if timeout 60s gh pr merge \
        --repo "$GITHUB_REPOSITORY" \
        --auto \
        --merge \
        --match-head-commit "$head_sha" \
        "$PR_NUMBER"; then
        echo "Native continuation requested for $pr_url at $head_sha."
        echo 'Required checks, human authority and the merge queue remain pending until GitHub confirms them.'
      else
        status=$?
        echo "Native continuation request failed or its outcome is unconfirmed: $pr_url" >&2
        echo 'Inspect native PR state before retrying; no mutation retry was attempted.' >&2
        exit "$status"
      fi
    '';
  };
  queueDependabot = pkgs.writeShellApplication {
    name = "finite-queue-dependabot";
    runtimeInputs = with pkgs; [bash gh jq];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      : "''${DEFAULT_BRANCH:?DEFAULT_BRANCH is required}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      : "''${GH_TOKEN:?GH_TOKEN is required}"

      pull_requests="$({
        gh api --paginate \
          "repos/''${GITHUB_REPOSITORY}/pulls?state=open&per_page=100" \
          --slurp
      })"

      jq -c \
        --arg branch "''${DEFAULT_BRANCH}" \
        --arg repository "''${GITHUB_REPOSITORY}" '
          add[] |
          select(.draft == false) |
          select(.user.login == "dependabot[bot]") |
          select(.head.repo.full_name == $repository) |
          select(.base.ref == $branch) |
          {sha: .head.sha, url: .html_url}
        ' <<<"''${pull_requests}" |
        while IFS= read -r pull_request; do
          head_sha="$(jq -er '.sha' <<<"''${pull_request}")"
          pr_url="$(jq -er '.url' <<<"''${pull_request}")"
          gh pr merge \
            --auto \
            --merge \
            --match-head-commit "''${head_sha}" \
            "''${pr_url}"
        done
    '';
  };
}
