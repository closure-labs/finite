{pkgs}: rec {
  releaseNotes = pkgs.writeShellApplication {
    name = "finite-release-notes";
    runtimeInputs = with pkgs; [bash coreutils gawk gnugrep gnused];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      version="''${1:?usage: release-notes.sh VERSION [CHANGELOG]}"
      changelog="''${2:-CHANGELOG.md}"

      [[ "''${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
        echo "Release notes require a stable semantic version: ''${version}" >&2
        exit 2
      }
      [[ -f "''${changelog}" ]] || {
        echo "Changelog does not exist: ''${changelog}" >&2
        exit 2
      }

      heading_prefix="## [''${version}] - "
      heading_count="$(grep -cF "''${heading_prefix}" "''${changelog}" || true)"
      [[ "''${heading_count}" -eq 1 ]] || {
        echo "Expected one changelog heading beginning with ''${heading_prefix}" >&2
        exit 2
      }

      escaped_version="''${version//./\\.}"
      grep -Eq "^## \\[''${escaped_version}\\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$" \
        "''${changelog}" || {
        echo "Changelog release heading must include an ISO date" >&2
        exit 2
      }

      awk -v heading_prefix="''${heading_prefix}" '
        index($0, heading_prefix) == 1 {
          found = 1
          next
        }
        found && /^## \[/ {
          exit
        }
        found && /^\[[^]]+\]:/ {
          exit
        }
        found {
          if (!started && $0 == "") {
            next
          }
          started = 1
          lines[++count] = $0
        }
        END {
          if (!found) {
            exit 2
          }
          while (count > 0 && lines[count] == "") {
            count--
          }
          for (line = 1; line <= count; line++) {
            print lines[line]
          }
        }
      ' "''${changelog}"
    '';
  };
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

          read_pr() {
            gh pr view "''${PR_NUMBER}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --json author,baseRefName,files,headRefName,headRefOid,headRepository,mergeStateStatus,state,title,url
          }

          validate_pr() {
            local candidate=$1
            [[ "$(jq -er '.state' <<<"''${candidate}")" == OPEN ]]
            [[ "$(jq -er '.title' <<<"''${candidate}")" == "''${EXPECTED_TITLE}" ]]
            [[ "$(jq -er '.author.login' <<<"''${candidate}")" == "''${EXPECTED_AUTHOR}" ]]
            [[ "$(jq -er '.baseRefName' <<<"''${candidate}")" == "''${DEFAULT_BRANCH}" ]]
            [[ "$(jq -er '.headRepository.nameWithOwner' <<<"''${candidate}")" == "''${GITHUB_REPOSITORY}" ]]
            [[ "$(jq -er '.headRefName' <<<"''${candidate}")" == "''${EXPECTED_BRANCH}" ]]
            if [[ -n "''${EXPECTED_FILES:-}" ]]; then
              jq -e --arg allowed "''${EXPECTED_FILES}" '
                ($allowed | split(",")) as $allowed_files |
                (.files | length) > 0 and
                all(.files[]; (.path as $path | $allowed_files | index($path)) != null)
              ' <<<"''${candidate}" >/dev/null || {
                echo 'Pull request changes files outside the declared automation scope' >&2
                return 1
              }
            fi
          }

          pr="$(read_pr)"
          validate_pr "''${pr}"
          if [[ "$(jq -er '.mergeStateStatus' <<<"''${pr}")" == BEHIND ]]; then
            gh pr update-branch "''${PR_NUMBER}" --repo "''${GITHUB_REPOSITORY}"
            pr="$(read_pr)"
            validate_pr "''${pr}"
          fi
          branch="$(jq -er '.headRefName' <<<"''${pr}")"
          head_sha="$(jq -er '.headRefOid' <<<"''${pr}")"
          pr_url="$(jq -er '.url' <<<"''${pr}")"

          dispatch_and_wait() {
            local workflow="$1"
            shift
            local previous_run_id run_id

            previous_run_id="$({
              gh run list \
                --repo "''${GITHUB_REPOSITORY}" \
                --workflow "''${workflow}" \
                --event workflow_dispatch \
                --branch "''${branch}" \
                --commit "''${head_sha}" \
                --limit 1 \
                --json databaseId \
                --jq '.[0].databaseId // empty'
            })"
            gh workflow run "''${workflow}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --ref "''${branch}" \
              "$@"

        run_id=""
            for _ in {1..24}; do
              run_id="$({
                gh run list \
                  --repo "''${GITHUB_REPOSITORY}" \
                  --workflow "''${workflow}" \
                  --event workflow_dispatch \
                  --branch "''${branch}" \
                  --commit "''${head_sha}" \
                  --limit 5 \
                  --json databaseId \
                  --jq ".[] | select((.databaseId | tostring) != \"''${previous_run_id}\") | .databaseId" |
                  head -n 1
              })"
              [[ -z "''${run_id}" ]] || break
              sleep 5
            done
            [[ -n "''${run_id}" ]] || {
              echo "Could not locate ''${workflow} validation run" >&2
              exit 1
            }

            gh run watch "''${run_id}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --exit-status
          }

      existing_ci_run=""
          for _ in {1..6}; do
            existing_ci_run="$({
              gh run list \
                --repo "''${GITHUB_REPOSITORY}" \
                --workflow build.yml \
                --event pull_request \
                --branch "''${branch}" \
                --commit "''${head_sha}" \
                --limit 1 \
                --json conclusion,databaseId,status \
                --jq '.[0] // empty'
            })"
            [[ -z "''${existing_ci_run}" ]] || break
            sleep 5
          done

          if [[ -n "''${existing_ci_run}" ]]; then
            existing_ci_run_id="$(jq -er '.databaseId' <<<"''${existing_ci_run}")"
            if [[ "$(jq -r '.conclusion // empty' <<<"''${existing_ci_run}")" == action_required ]]; then
              gh api \
                --method POST \
                "repos/''${GITHUB_REPOSITORY}/actions/runs/''${existing_ci_run_id}/approve"
            fi
            gh run watch "''${existing_ci_run_id}" \
              --repo "''${GITHUB_REPOSITORY}" \
              --exit-status
          else
            dispatch_and_wait build.yml -f validate_only=true
          fi
          gh pr merge \
            --repo "''${GITHUB_REPOSITORY}" \
            --auto \
            --merge \
            --match-head-commit "''${head_sha}" \
            "''${pr_url}"
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
  packageCleanup = pkgs.writeShellApplication {
    name = "finite-package-cleanup";
    runtimeInputs = with pkgs; [bash gh jq];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      : "''${DRY_RUN:=true}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      : "''${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER is required}"

      owner="''${GITHUB_REPOSITORY_OWNER}"
      package="''${GITHUB_REPOSITORY#*/}"
      # Build and installer caches use isolated sibling packages. Querying only
      # the primary image package keeps cache retention outside this cleanup.
      obsolete_tags='[]'

      delete_version() {
        local package_name="$1"
        local version_id="$2"
        if [[ "''${DRY_RUN}" != true ]]; then
          gh api --method DELETE \
            "/users/''${owner}/packages/container/''${package_name}/versions/''${version_id}"
        fi
      }

      versions="$({
        gh api --paginate "/users/''${owner}/packages/container/''${package}/versions?per_page=100" --slurp
      })"
      jq -c --argjson obsolete "''${obsolete_tags}" '
        add[] | . as $version | (.metadata.container.tags // []) as $tags |
        select(($tags | length) > 0) |
        select(all($tags[]; $obsolete | index(.) != null)) |
        {id: $version.id, tags: $tags}
      ' <<<"''${versions}" |
        while IFS= read -r candidate; do
          version_id="$(jq -r '.id' <<<"''${candidate}")"
          echo "Obsolete package version ''${version_id}: $(jq -r '.tags | join(", ")' <<<"''${candidate}")"
          delete_version "''${package}" "''${version_id}"
        done
    '';
  };
}
