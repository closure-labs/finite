{
  generated,
  imageVerify,
  pkgs,
  sbomAttestation,
}:
pkgs.writeShellApplication {
  name = "finite-release-control";
  runtimeInputs = with pkgs; [coreutils findutils gh git gnugrep gzip jq oras skopeo];
  text = ''
    set -euo pipefail

    usage() {
      cat >&2 <<'EOF'
    usage: finite-release-control <select-version|resolve-source|candidate-run|
             verify-graph|promote|next-version|wait-pr>
    EOF
    }

    gh_command="''${FINITE_GH:-gh}"
    skopeo_command="''${FINITE_SKOPEO:-skopeo}"
    oras_command="''${FINITE_ORAS:-oras}"
    image_verify_command="''${FINITE_IMAGE_VERIFY:-${imageVerify}/bin/finite-image-verify}"
    sbom_command="''${FINITE_SBOM_ATTESTATION:-${sbomAttestation}/bin/finite-sbom-attestation}"
    generated_root="''${FINITE_GENERATED_ROOT:-${generated}}"
    matrix="''${generated_root}/bootc/generated/image-matrix.json"

    remote_main_sha() {
      if [[ -n "''${FINITE_REMOTE_SHA:-}" ]]; then
        printf '%s\n' "''${FINITE_REMOTE_SHA}"
      else
        "''${gh_command}" api "repos/''${GITHUB_REPOSITORY}/commits/main" --jq .sha
      fi
    }

    wait_for_pr() {
      : "''${PR_NUMBER:?PR_NUMBER is required}"
      local attempts="''${FINITE_WAIT_ATTEMPTS:-480}"
      local pull_request source_sha
      for ((attempt = 1; attempt <= attempts; attempt++)); do
        pull_request="$("''${gh_command}" pr view "''${PR_NUMBER}" \
          --json mergeCommit,mergedAt,state)"
        source_sha="$(jq -r '.mergeCommit.oid // empty' <<<"''${pull_request}")"
        if [[ -n "$(jq -r '.mergedAt // empty' <<<"''${pull_request}")" ]]; then
          [[ "''${source_sha}" =~ ^[0-9a-f]{40}$ ]] || {
            echo "Merged pull request has no valid merge commit" >&2
            return 1
          }
          printf '%s\n' "''${source_sha}"
          return 0
        fi
        [[ "$(jq -r '.state' <<<"''${pull_request}")" == OPEN ]] || {
          echo "Pull request closed without merging" >&2
          return 1
        }
        sleep "''${FINITE_WAIT_DELAY:-15}"
      done
      echo "Timed out waiting for pull request ''${PR_NUMBER}" >&2
      return 1
    }

    select_version() {
      : "''${REQUESTED_BUMP:?REQUESTED_BUMP is required}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      [[ "''${GITHUB_REF:-refs/heads/main}" == refs/heads/main ]] || {
        echo "Releases may run only from main" >&2
        return 1
      }
      initial_sha="$(git rev-parse HEAD)"
      [[ -z "''${GITHUB_SHA:-}" || "''${initial_sha}" == "''${GITHUB_SHA}" ]] || {
        echo "Checkout does not match the dispatched commit" >&2
        return 1
      }
      source_version="$(<VERSION)"
      [[ "''${source_version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-dev\.[0-9]+)?$ ]] || {
        echo "VERSION must contain X.Y.Z or X.Y.Z-dev.N" >&2
        return 1
      }
      last_tag="$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' --sort=-v:refname |
        grep -E '^v[0-9]+\.[0-9]+\.[0-9]+$' | head -n 1 || true)"
      if [[ -n "''${last_tag}" ]]; then
        git merge-base --is-ancestor "''${last_tag}" HEAD || {
          echo "Latest release tag ''${last_tag} is not an ancestor of main" >&2
          return 1
        }
        meaningful_commits="$(git log "''${last_tag}..HEAD" --format='%H' \
          --invert-grep --grep='^Start Finite [0-9]\+\.[0-9]\+\.[0-9]\+-dev\.[0-9]\+$')"
        [[ -n "''${meaningful_commits}" ]] || {
          echo "No releasable commits exist after ''${last_tag}" >&2
          return 1
        }
      fi

      if [[ "''${source_version}" != *-dev.* ]]; then
        version="''${source_version}"
        selected_bump=staged
        if [[ -n "''${last_tag}" ]]; then
          last_version="''${last_tag#v}"
          newest_version="$(printf '%s\n' "''${last_version}" "''${version}" | sort -V | tail -n 1)"
          [[ "''${version}" != "''${last_version}" && "''${newest_version}" == "''${version}" ]] || {
            echo "Staged release ''${version} must be newer than ''${last_version}" >&2
            return 1
          }
        fi
      elif [[ -z "''${last_tag}" ]]; then
        version="''${source_version%%-dev.*}"
        selected_bump=initial
      else
        base_version="''${last_tag#v}"
        IFS=. read -r major minor patch_number <<<"''${base_version}"
        selected_bump="''${REQUESTED_BUMP}"
        if [[ "''${selected_bump}" == auto ]]; then
          release_log="$(git log "''${last_tag}..HEAD" --format='%s%n%b' \
            --invert-grep --grep='^Start Finite [0-9]\+\.[0-9]\+\.[0-9]\+-dev\.[0-9]\+$')"
          if grep -Eq '(^[[:alnum:]-]+(\([^)]*\))?!:)|(^BREAKING[ -]CHANGE:)' \
            <<<"''${release_log}"; then
            selected_bump=major
          elif grep -Eq '^feat(\([^)]*\))?:' <<<"''${release_log}"; then
            selected_bump=minor
          else
            selected_bump='patch'
          fi
        fi
        case "''${selected_bump}" in
          major) version="$((major + 1)).0.0" ;;
          minor) version="''${major}.$((minor + 1)).0" ;;
          patch) version="''${major}.''${minor}.$((patch_number + 1))" ;;
          *) echo "Unsupported release bump: ''${selected_bump}" >&2; return 2 ;;
        esac
      fi
      tag="v''${version}"
      if git rev-parse --verify --quiet "refs/tags/''${tag}"; then
        echo "Release tag ''${tag} already exists" >&2
        return 1
      fi
      remote_sha="$(remote_main_sha)"
      [[ "''${remote_sha}" == "''${initial_sha}" ]] || {
        echo "Main advanced after this release was dispatched" >&2
        return 1
      }
      printf '%s\n' "''${version}" >VERSION
      jq -cn \
        --arg initial_sha "''${initial_sha}" \
        --arg source_version "''${source_version}" \
        --arg tag "''${tag}" \
        --arg version "''${version}" \
        --arg selected_bump "''${selected_bump}" '{
          schema: 1,
          initial_sha: $initial_sha,
          source_version: $source_version,
          tag: $tag,
          version: $version,
          selected_bump: $selected_bump
        }'
    }

    resolve_source() {
      : "''${VERSION:?VERSION is required}"
      if [[ -n "''${SOURCE_SHA:-}" ]]; then
        source_sha="''${SOURCE_SHA}"
      elif [[ -n "''${PR_NUMBER:-}" && "''${PR_OPERATION:-}" != closed ]]; then
        source_sha="$(wait_for_pr)"
      else
        : "''${INITIAL_SHA:?INITIAL_SHA is required without a pull request}"
        source_sha="$(remote_main_sha)"
        [[ "''${source_sha}" == "''${INITIAL_SHA}" ]] || {
          echo "Main advanced without the release version pull request" >&2
          return 1
        }
      fi
      [[ "''${source_sha}" =~ ^[0-9a-f]{40}$ ]] || {
        echo "Invalid release source SHA: ''${source_sha}" >&2
        return 2
      }
      if [[ "''${FINITE_SKIP_CHECKOUT:-false}" != true ]]; then
        git fetch origin main
        [[ "$(git rev-parse origin/main)" == "''${source_sha}" ]]
        git checkout --detach "''${source_sha}"
      fi
      [[ "$(<VERSION)" == "''${VERSION}" ]]
      [[ "$(remote_main_sha)" == "''${source_sha}" ]] || {
        echo "Main advanced beyond the release source" >&2
        return 1
      }
      if git rev-parse --verify --quiet "refs/tags/v''${VERSION}" ||
        git ls-remote --exit-code --tags origin "refs/tags/v''${VERSION}" >/dev/null 2>&1; then
        echo "Release tag v''${VERSION} already exists" >&2
        return 1
      fi
      jq -cn --arg source_sha "''${source_sha}" --arg version "''${VERSION}" '{
        schema: 1,
        source_sha: $source_sha,
        version: $version
      }'
    }

    candidate_run() {
      : "''${SOURCE_SHA:?SOURCE_SHA is required}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      run_id=
      if [[ "''${FORCE_REBUILD:-false}" != true ]]; then
        for _ in {1..6}; do
          run_id="$("''${gh_command}" run list --workflow build.yml \
            --commit "''${SOURCE_SHA}" --limit 20 \
            --json conclusion,databaseId,status \
            --jq '.[] | select(.status == "queued" or .status == "in_progress" or .conclusion == "success") | .databaseId' |
            head -n 1)"
          [[ -z "''${run_id}" ]] || break
          sleep "''${FINITE_CANDIDATE_DELAY:-5}"
        done
      fi
      if [[ -z "''${run_id}" ]]; then
        [[ "$(remote_main_sha)" == "''${SOURCE_SHA}" ]] || {
          echo "Main advanced before the candidate build was dispatched" >&2
          return 1
        }
        previous_run_id="$("''${gh_command}" run list --workflow build.yml \
          --event workflow_dispatch --commit "''${SOURCE_SHA}" --limit 1 \
          --json databaseId --jq '.[0].databaseId // empty')"
        "''${gh_command}" workflow run build.yml --ref main -f force=true
        for _ in {1..24}; do
          run_id="$("''${gh_command}" run list --workflow build.yml \
            --event workflow_dispatch --commit "''${SOURCE_SHA}" --limit 5 \
            --json databaseId \
            --jq ".[] | select((.databaseId | tostring) != \"''${previous_run_id}\") | .databaseId" |
            head -n 1)"
          [[ -z "''${run_id}" ]] || break
          sleep "''${FINITE_CANDIDATE_DELAY:-5}"
        done
      fi
      [[ "''${run_id}" =~ ^[0-9]+$ ]] || {
        echo "Could not locate the release-candidate build" >&2
        return 1
      }
      jq -cn --argjson run_id "''${run_id}" '{schema: 1, run_id: $run_id}'
    }

    profiles_are_current() {
      local entry expected_input metadata primary_tag profile
      while IFS= read -r entry; do
        profile="$(jq -r '.profile' <<<"''${entry}")"
        primary_tag="$(jq -r '.tags | split(" ")[0]' <<<"''${entry}")"
        expected_input="$(jq -r '.build_input' <<<"''${entry}")"
        metadata="$("''${skopeo_command}" inspect --retry-times 3 \
          "docker://''${IMAGE_REF}:''${primary_tag}")" || return 1
        [[ "$(jq -er '.Labels["org.opencontainers.image.revision"]' <<<"''${metadata}")" == "''${SOURCE_SHA}" ]] || return 1
        [[ "$(jq -er '.Labels["org.opencontainers.image.version"]' <<<"''${metadata}")" == "''${VERSION}" ]] || return 1
        [[ "$(jq -er '.Labels["io.finite.build.profile"]' <<<"''${metadata}")" == "''${profile}" ]] || return 1
        [[ "$(jq -er '.Labels["io.finite.build.input"]' <<<"''${metadata}")" == "''${expected_input}" ]] || return 1
      done < <(jq -c '.[]' "''${matrix}")
    }

    verify_graph() {
      : "''${SOURCE_SHA:?SOURCE_SHA is required}"
      : "''${VERSION:?VERSION is required}"
      : "''${IMAGE_REF:?IMAGE_REF is required}"
      if ! profiles_are_current; then
        echo "Published graph is stale; forcing a complete candidate build" >&2
        repair_report="$(FORCE_REBUILD=true candidate_run)"
        run_id="$(jq -er '.run_id' <<<"''${repair_report}")"
        "''${gh_command}" run watch "''${run_id}" --exit-status
        profiles_are_current
      fi
      profile_count="$(jq 'length' "''${matrix}")"
      jq -cn --argjson profile_count "''${profile_count}" '{
        schema: 1,
        profile_count: $profile_count,
        graph_verified: true
      }'
    }

    promote() {
      : "''${SOURCE_SHA:?SOURCE_SHA is required}"
      : "''${VERSION:?VERSION is required}"
      : "''${IMAGE_REF:?IMAGE_REF is required}"
      : "''${COSIGN_IDENTITY:?COSIGN_IDENTITY is required}"
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
      : "''${REGISTRY_AUTH_FILE:?REGISTRY_AUTH_FILE is required}"
      : "''${SBOM_SIGNER_WORKFLOW:?SBOM_SIGNER_WORKFLOW is required}"
      images='[]'
      install -d -m 0755 release-sboms
      while IFS= read -r entry; do
        profile="$(jq -r '.profile' <<<"''${entry}")"
        primary_tag="$(jq -r '.tags | split(" ")[0]' <<<"''${entry}")"
        expected_input="$(jq -r '.build_input' <<<"''${entry}")"
        metadata="$("''${skopeo_command}" inspect --retry-times 3 \
          "docker://''${IMAGE_REF}:''${primary_tag}")"
        digest="$(jq -er '.Digest' <<<"''${metadata}")"
        base_digest="$(jq -er '.Labels["org.opencontainers.image.base.digest"]' <<<"''${metadata}")"
        build_input="$(jq -er '.Labels["io.finite.build.input"]' <<<"''${metadata}")"
        "''${image_verify_command}" \
          --image "''${IMAGE_REF}" \
          --digest "''${digest}" \
          --cosign-identity "''${COSIGN_IDENTITY}" \
          --source-sha "''${SOURCE_SHA}" \
          --provenance-workflow "''${GITHUB_REPOSITORY}/.github/workflows/build-profile.yml" \
          --sbom-workflow "''${SBOM_SIGNER_WORKFLOW}" \
          --expect-label "io.finite.build.profile=''${profile}" \
          --expect-label "io.finite.build.input=''${expected_input}" \
          --expect-label "org.opencontainers.image.revision=''${SOURCE_SHA}" \
          --expect-label "org.opencontainers.image.version=''${VERSION}" >/dev/null

        immutable_ref="''${IMAGE_REF}@''${digest}"
        release_tag="''${profile}-v''${VERSION}"
        "''${oras_command}" tag --registry-config "''${REGISTRY_AUTH_FILE}" \
          "''${immutable_ref}" "''${release_tag}"
        release_digest="$("''${skopeo_command}" inspect --retry-times 3 \
          --format '{{.Digest}}' "docker://''${IMAGE_REF}:''${release_tag}")"
        [[ "''${release_digest}" == "''${digest}" ]]

        sbom_dir="$(mktemp -d -p "''${RUNNER_TEMP:-''${TMPDIR:-/tmp}}" \
          "finite-''${profile}-sbom.XXXXXX")"
        sbom="''${sbom_dir}/sbom.spdx.json"
        SBOM_IMAGE_DIGEST="''${digest}" \
        SBOM_IMAGE_REF="''${IMAGE_REF}" \
        SBOM_SIGNER_WORKFLOW="''${SBOM_SIGNER_WORKFLOW}" \
        SBOM_SOURCE_DIGEST="''${SOURCE_SHA}" \
          "''${sbom_command}" extract "''${sbom}"
        sbom_asset="finite-''${profile}-v''${VERSION}.spdx.json.gz"
        gzip -9c "''${sbom}" >"release-sboms/''${sbom_asset}"
        rm -f -- "''${sbom}"
        rmdir -- "''${sbom_dir}"

        image="$(jq -cn \
          --arg profile "''${profile}" \
          --arg channel_tag "''${primary_tag}" \
          --arg release_tag "''${release_tag}" \
          --arg digest "''${digest}" \
          --arg base_digest "''${base_digest}" \
          --arg build_input "''${build_input}" \
          --arg sbom_asset "''${sbom_asset}" '{
            profile: $profile,
            channel_tag: $channel_tag,
            release_tag: $release_tag,
            digest: $digest,
            base_digest: $base_digest,
            build_input: $build_input,
            sbom_asset: $sbom_asset
          }')"
        images="$(jq -c --argjson image "''${image}" '. + [$image]' <<<"''${images}")"
      done < <(jq -c '.[]' "''${matrix}")

      jq -n \
        --arg version "''${VERSION}" \
        --arg source_commit "''${SOURCE_SHA}" \
        --arg image "''${IMAGE_REF}" \
        --argjson images "''${images}" '{
          version: $version,
          source_commit: $source_commit,
          image: $image,
          images: $images
        }' >release-manifest.json
      sha256sum release-manifest.json >release-manifest.json.sha256
      profile_count="$(jq 'length' <<<"''${images}")"
      jq -cn \
        --arg version "''${VERSION}" \
        --arg manifest release-manifest.json \
        --argjson profile_count "''${profile_count}" '{
          schema: 1,
          version: $version,
          manifest: $manifest,
          profile_count: $profile_count
        }'
    }

    next_version() {
      : "''${SOURCE_SHA:?SOURCE_SHA is required}"
      : "''${VERSION:?VERSION is required}"
      [[ "''${VERSION}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || {
        echo "A stable version is required" >&2
        return 2
      }
      IFS=. read -r major minor patch_number <<<"''${VERSION}"
      next="''${major}.''${minor}.$((patch_number + 1))-dev.0"
      [[ "$(remote_main_sha)" == "''${SOURCE_SHA}" ]] || {
        echo "Main advanced before the post-release version commit" >&2
        return 1
      }
      printf '%s\n' "''${next}" >VERSION
      jq -cn --arg next_version "''${next}" '{schema: 1, next_version: $next_version}'
    }

    command="''${1:-}"
    [[ -n "''${command}" ]] || { usage; exit 2; }
    shift
    (($# == 0)) || { usage; exit 2; }
    case "''${command}" in
      select-version) select_version ;;
      resolve-source) resolve_source ;;
      candidate-run) candidate_run ;;
      verify-graph) verify_graph ;;
      promote) promote ;;
      next-version) next_version ;;
      wait-pr)
        source_sha="$(wait_for_pr)"
        jq -cn --arg source_sha "''${source_sha}" '{schema: 1, source_sha: $source_sha, merged: true}'
        ;;
      *) usage; exit 2 ;;
    esac
  '';
}
