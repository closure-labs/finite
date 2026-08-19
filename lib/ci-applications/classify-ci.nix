{
  classifyChanges,
  pkgs,
}:
pkgs.writeShellApplication {
  name = "purplefin-classify-ci";
  runtimeInputs = with pkgs; [bash classifyChanges coreutils git jq];
  text = ''
    repo_root="''${PURPLEFIN_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Purplefin repository root" >&2
      exit 2
    }
    cd "''${repo_root}"
    set -euo pipefail

    output_file="''${1:?usage: purplefin-classify-ci GITHUB_OUTPUT}"
    event_name="''${EVENT_NAME:?EVENT_NAME is required}"
    temp_root="$(mktemp -d)"
    trap 'rm -rf -- "''${temp_root}"' EXIT

    emit() {
      local images=$1 installer=$2 status=$3 scope=$4
      local base_sha=''${5:-} head_sha=''${6:-} classification
      classification="$(jq -cn \
        --arg base "''${base_sha}" \
        --arg head "''${head_sha}" \
        --arg scope "''${scope}" \
        --arg status "''${status}" \
        --argjson images "''${images}" \
        --argjson installer "''${installer}" '
        {
          schema: 1,
          diff: {
            status: $status,
            base: (if $base == "" then null else $base end),
            head: (if $head == "" then null else $head end)
          },
          validation: {
            images: {required: $images, scope: $scope},
            installer: {required: $installer}
          }
        }
      ')"
      printf 'classification=%s\n' "''${classification}" >>"''${output_file}"
    }

    select_all() {
      echo 'Could not establish a trustworthy event diff; requiring all expensive validations' >&2
      emit true true fallback all "''${1:-}" "''${2:-}"
    }

    classify_range() {
      local base_sha=$1
      local head_sha=$2
      local allow_release_metadata=''${3:-false}
      local require_ancestor=''${4:-false}
      local changed_paths="''${temp_root}/changed-paths"

      if [[ ! "''${base_sha}" =~ ^[0-9a-f]{40}$ || ! "''${head_sha}" =~ ^[0-9a-f]{40}$ ]] ||
        ! git cat-file -e "''${base_sha}^{commit}" 2>/dev/null ||
        ! git cat-file -e "''${head_sha}^{commit}" 2>/dev/null; then
        select_all "''${base_sha}" "''${head_sha}"
        return
      fi

      if [[ "''${require_ancestor}" == true ]] &&
        ! git merge-base --is-ancestor "''${base_sha}" "''${head_sha}"; then
        echo 'Merge-group base is not an ancestor of its head' >&2
        select_all "''${base_sha}" "''${head_sha}"
        return
      fi

      # Disable rename detection so both sides of a rename are classified. A
      # relevant source moved into an ignored directory must remain relevant.
      if ! git diff --no-renames --name-only --diff-filter=ACDMRT \
        "''${base_sha}" "''${head_sha}" >"''${changed_paths}"; then
        select_all "''${base_sha}" "''${head_sha}"
        return
      fi
      if [[ "''${allow_release_metadata}" == true ]] &&
        grep -qxF VERSION "''${changed_paths}" &&
        ! grep -Ev '^(VERSION|CHANGELOG\.md|README\.md|docs/.*)$' "''${changed_paths}" | grep -q .; then
        echo 'Release metadata only; skipping image and installer candidates' >&2
        emit false false classified none "''${base_sha}" "''${head_sha}"
        return
      fi

      images="$(purplefin-classify-changes images <"''${changed_paths}")"
      installer="$(purplefin-classify-changes installer <"''${changed_paths}")"
      if [[ "''${images}" == true ]]; then
        scope=changed
      else
        scope=none
      fi
      emit "''${images}" "''${installer}" classified "''${scope}" "''${base_sha}" "''${head_sha}"
    }

    case "''${event_name}" in
    pull_request)
      classify_range \
        "''${PULL_REQUEST_BASE_SHA:-}" \
        "''${PULL_REQUEST_HEAD_SHA:-}" \
        true
      ;;
    merge_group)
      classify_range \
        "''${MERGE_GROUP_BASE_SHA:-}" \
        "''${MERGE_GROUP_HEAD_SHA:-}" \
        true \
        true
      ;;
    push)
      before_sha="''${PUSH_BEFORE_SHA:-}"
      after_sha="''${PUSH_AFTER_SHA:-}"
      if [[ "''${before_sha}" =~ ^0{40}$ ]]; then
        select_all "''${before_sha}" "''${after_sha}"
      else
        classify_range "''${before_sha}" "''${after_sha}"
      fi
      ;;
    schedule)
      # Scheduled runs deliberately probe every profile for independently managed
      # RPM updates even when the repository itself has not changed.
      emit true false predetermined all
      ;;
    workflow_dispatch)
      if [[ "''${FORCE_REBUILD:-false}" == true || "''${VALIDATE_ONLY:-false}" != true ]]; then
        emit true false predetermined all
      else
        head_sha="$(git rev-parse HEAD)"
        if base_sha="$(git merge-base "''${DEFAULT_BRANCH_REF:-origin/main}" "''${head_sha}" 2>/dev/null)"; then
          classify_range "''${base_sha}" "''${head_sha}" true
        else
          select_all "''${DEFAULT_BRANCH_REF:-origin/main}" "''${head_sha}"
        fi
      fi
      ;;
    *)
      echo "Unknown event ''${event_name}" >&2
      select_all
      ;;
    esac
  '';
}
