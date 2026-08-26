{pkgs}: rec {
  sbomAttestation = pkgs.writeShellApplication {
    name = "finite-sbom-attestation";
    runtimeInputs = with pkgs; [coreutils gh jq];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      predicate_type='https://spdx.dev/Document/v2.3'
      maximum_size=$((16 * 1024 * 1024))

      usage() {
        cat >&2 <<'EOF'
      usage: sbom.sh extract OUTPUT
             sbom.sh generate OUTPUT
             sbom.sh validate SBOM
             sbom.sh equivalent LEFT RIGHT
      EOF
      }

      resolve_tool() {
        local override="$1"
        local command_name="$2"
        local resolved
        if [[ -n "''${override}" ]]; then
          resolved="''${override}"
        else
          resolved="$(command -v "''${command_name}" || true)"
        fi
        [[ -n "''${resolved}" && -x "''${resolved}" ]] || {
          echo "Required command is unavailable: ''${command_name}" >&2
          return 2
        }
        printf '%s\n' "''${resolved}"
      }

      validate_sbom() {
        local sbom="$1"
        local size
        [[ -f "''${sbom}" ]] || {
          echo "SBOM does not exist: ''${sbom}" >&2
          return 2
        }
        jq -e '
          type == "object" and
          (.spdxVersion | type == "string" and startswith("SPDX-")) and
          (.packages | type == "array") and
          any(.packages[]?; any(.externalRefs[]?; .referenceType == "purl")) and
          all(.packages[]?; all(.externalRefs[]?; .referenceType != "cpe23Type"))
        ' "''${sbom}" >/dev/null || {
          echo "SBOM is not a normalized SPDX package document: ''${sbom}" >&2
          return 1
        }
        size="$(wc -c <"''${sbom}")"
        if ((size > maximum_size)); then
          printf 'SBOM is %d bytes; actions/attest accepts at most %d bytes.\n' \
            "''${size}" "''${maximum_size}" >&2
          return 1
        fi
      }

      equivalent_sboms() {
        local left="$1"
        local right="$2"
        validate_sbom "''${left}"
        validate_sbom "''${right}"
        cmp --silent <(jq -Sc . "''${left}") <(jq -Sc . "''${right}")
      }

      extract_attestation() {
        local output="$1"
        local gh_command verification predicate
        : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        : "''${SBOM_SIGNER_WORKFLOW:?SBOM_SIGNER_WORKFLOW is required}"
        : "''${SBOM_SOURCE_DIGEST:?SBOM_SOURCE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]
        [[ "''${SBOM_SOURCE_DIGEST}" =~ ^[0-9a-f]{40}$ ]]

        gh_command="$(resolve_tool "''${FINITE_GH:-}" gh)"
        verification="$(mktemp "''${TMPDIR:-/tmp}/finite-sbom-verification.XXXXXX")"
        predicate="$(mktemp "''${TMPDIR:-/tmp}/finite-sbom-predicate.XXXXXX")"
        if ! "''${gh_command}" attestation verify \
          "oci://''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}" \
          --bundle-from-oci \
          --repo "''${GITHUB_REPOSITORY}" \
          --signer-workflow "''${SBOM_SIGNER_WORKFLOW}" \
          --source-digest "''${SBOM_SOURCE_DIGEST}" \
          --predicate-type "''${predicate_type}" \
          --format json >"''${verification}" 2>/dev/null; then
          rm -f -- "''${verification}" "''${predicate}"
          return 3
        fi
        if ! jq -ce \
          --arg digest "''${SBOM_IMAGE_DIGEST#sha256:}" \
          --arg predicate_type "''${predicate_type}" '
            [
              .[]?.verificationResult.statement |
              select(.predicateType == $predicate_type) |
              select(any(.subject[]?; .digest.sha256 == $digest)) |
              .predicate
            ] |
            unique |
            if length == 1 then
              .[0]
            else
              error("expected exactly one distinct verified SPDX predicate")
            end
          ' "''${verification}" >"''${predicate}"; then
          rm -f -- "''${verification}" "''${predicate}"
          return 1
        fi
        rm -f -- "''${verification}"
        if ! validate_sbom "''${predicate}"; then
          rm -f -- "''${predicate}"
          return 1
        fi
        mv -- "''${predicate}" "''${output}"
      }

      generate_sbom() {
        local output="$1"
        local repo_root podman_command syft_command nix_store_command
        local syft_store scan_image generated
        local -a auth_args syft_closure syft_mounts
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]

        repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/.github/syft.yaml" ]] || {
          echo "Run this command from the Finite repository root" >&2
          return 2
        }
        podman_command="$(resolve_tool "''${FINITE_PODMAN:-}" podman)"
        syft_command="$(resolve_tool "''${FINITE_SYFT:-}" syft)"
        nix_store_command="$(resolve_tool "''${FINITE_NIX_STORE:-}" nix-store)"
        syft_store="''${FINITE_SYFT_STORE:-$(dirname "$(dirname "$(readlink -f "''${syft_command}")")")}"

        mapfile -t syft_closure < <(
          "''${nix_store_command}" --query --requisites "''${syft_store}"
        )
        syft_mounts=()
        for store_path in "''${syft_closure[@]}"; do
          syft_mounts+=(--volume "''${store_path}:''${store_path}:ro")
        done

        auth_args=()
        if [[ -n "''${REGISTRY_AUTH_FILE:-}" ]]; then
          auth_args+=(--authfile "''${REGISTRY_AUTH_FILE}")
        fi
        if [[ -n "''${SBOM_LOCAL_IMAGE:-}" ]]; then
          scan_image="''${SBOM_LOCAL_IMAGE}"
        else
          scan_image="$(''${podman_command} pull --quiet "''${auth_args[@]}" \
            "''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}")"
        fi

        generated="$(mktemp "''${TMPDIR:-/tmp}/finite-sbom-generated.XXXXXX")"
        if ! "''${podman_command}" run --rm --pull=never \
          --cpus 4 \
          --env SYFT_CACHE_DIR=/tmp/syft-cache \
          --memory 4g \
          --network none \
          --security-opt label=disable \
          --user 0 \
          --volume "''${repo_root}/.github/syft.yaml:/run/finite-syft.yaml:ro" \
          "''${syft_mounts[@]}" \
          --entrypoint "''${syft_command}" \
          "''${scan_image}" \
          scan dir:/ \
            --config /run/finite-syft.yaml \
            --exclude './nix/store/**' \
            --source-name "''${SBOM_IMAGE_REF}" \
            --source-version "''${SBOM_IMAGE_DIGEST}" \
            --output spdx-json |
          jq -c '
            .packages |= map(
              if has("externalRefs") then
                .externalRefs |= map(
                  select(.referenceType != "cpe23Type")
                ) |
                if (.externalRefs | length) == 0 then
                  del(.externalRefs)
                else
                  .
                end
              else
                .
              end
            )
          ' >"''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        if ! validate_sbom "''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        mv -- "''${generated}" "''${output}"
      }

      command="''${1:-}"
      [[ -n "''${command}" ]] || {
        usage
        exit 2
      }
      shift
      case "''${command}" in
        extract)
          (( $# == 1 )) || { usage; exit 2; }
          extract_attestation "$1"
          ;;
        generate)
          (( $# == 1 )) || { usage; exit 2; }
          generate_sbom "$1"
          ;;
        validate)
          (( $# == 1 )) || { usage; exit 2; }
          validate_sbom "$1"
          ;;
        equivalent)
          (( $# == 2 )) || { usage; exit 2; }
          equivalent_sboms "$1" "$2"
          ;;
        *) usage; exit 2 ;;
      esac
    '';
  };
  imageSbom = pkgs.writeShellApplication {
    name = "finite-image-sbom";
    runtimeInputs = with pkgs; [coreutils gh jq syft];
    text = ''
      repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
      [[ -f "''${repo_root}/flake.nix" ]] || {
        echo "Run this command from the Finite repository root" >&2
        exit 2
      }
      cd "''${repo_root}"
      set -euo pipefail

      predicate_type='https://spdx.dev/Document/v2.3'
      maximum_size=$((16 * 1024 * 1024))

      usage() {
        cat >&2 <<'EOF'
      usage: sbom.sh extract OUTPUT
             sbom.sh generate OUTPUT
             sbom.sh validate SBOM
             sbom.sh equivalent LEFT RIGHT
      EOF
      }

      resolve_tool() {
        local override="$1"
        local command_name="$2"
        local resolved
        if [[ -n "''${override}" ]]; then
          resolved="''${override}"
        else
          resolved="$(command -v "''${command_name}" || true)"
        fi
        [[ -n "''${resolved}" && -x "''${resolved}" ]] || {
          echo "Required command is unavailable: ''${command_name}" >&2
          return 2
        }
        printf '%s\n' "''${resolved}"
      }

      validate_sbom() {
        local sbom="$1"
        local size
        [[ -f "''${sbom}" ]] || {
          echo "SBOM does not exist: ''${sbom}" >&2
          return 2
        }
        jq -e '
          type == "object" and
          (.spdxVersion | type == "string" and startswith("SPDX-")) and
          (.packages | type == "array") and
          any(.packages[]?; any(.externalRefs[]?; .referenceType == "purl")) and
          all(.packages[]?; all(.externalRefs[]?; .referenceType != "cpe23Type"))
        ' "''${sbom}" >/dev/null || {
          echo "SBOM is not a normalized SPDX package document: ''${sbom}" >&2
          return 1
        }
        size="$(wc -c <"''${sbom}")"
        if ((size > maximum_size)); then
          printf 'SBOM is %d bytes; actions/attest accepts at most %d bytes.\n' \
            "''${size}" "''${maximum_size}" >&2
          return 1
        fi
      }

      equivalent_sboms() {
        local left="$1"
        local right="$2"
        validate_sbom "''${left}"
        validate_sbom "''${right}"
        cmp --silent <(jq -Sc . "''${left}") <(jq -Sc . "''${right}")
      }

      extract_attestation() {
        local output="$1"
        local gh_command verification predicate
        : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        : "''${SBOM_SIGNER_WORKFLOW:?SBOM_SIGNER_WORKFLOW is required}"
        : "''${SBOM_SOURCE_DIGEST:?SBOM_SOURCE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]
        [[ "''${SBOM_SOURCE_DIGEST}" =~ ^[0-9a-f]{40}$ ]]

        gh_command="$(resolve_tool "''${FINITE_GH:-}" gh)"
        verification="$(mktemp "''${TMPDIR:-/tmp}/finite-sbom-verification.XXXXXX")"
        predicate="$(mktemp "''${TMPDIR:-/tmp}/finite-sbom-predicate.XXXXXX")"
        if ! "''${gh_command}" attestation verify \
          "oci://''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}" \
          --bundle-from-oci \
          --repo "''${GITHUB_REPOSITORY}" \
          --signer-workflow "''${SBOM_SIGNER_WORKFLOW}" \
          --source-digest "''${SBOM_SOURCE_DIGEST}" \
          --predicate-type "''${predicate_type}" \
          --format json >"''${verification}" 2>/dev/null; then
          rm -f -- "''${verification}" "''${predicate}"
          return 3
        fi
        if ! jq -ce \
          --arg digest "''${SBOM_IMAGE_DIGEST#sha256:}" \
          --arg predicate_type "''${predicate_type}" '
            [
              .[]?.verificationResult.statement |
              select(.predicateType == $predicate_type) |
              select(any(.subject[]?; .digest.sha256 == $digest)) |
              .predicate
            ] |
            unique |
            if length == 1 then
              .[0]
            else
              error("expected exactly one distinct verified SPDX predicate")
            end
          ' "''${verification}" >"''${predicate}"; then
          rm -f -- "''${verification}" "''${predicate}"
          return 1
        fi
        rm -f -- "''${verification}"
        if ! validate_sbom "''${predicate}"; then
          rm -f -- "''${predicate}"
          return 1
        fi
        mv -- "''${predicate}" "''${output}"
      }

      generate_sbom() {
        local output="$1"
        local repo_root podman_command syft_command nix_store_command
        local syft_store scan_image generated
        local -a auth_args syft_closure syft_mounts
        : "''${SBOM_IMAGE_REF:?SBOM_IMAGE_REF is required}"
        : "''${SBOM_IMAGE_DIGEST:?SBOM_IMAGE_DIGEST is required}"
        [[ "''${SBOM_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]]

        repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
        [[ -f "''${repo_root}/.github/syft.yaml" ]] || {
          echo "Run this command from the Finite repository root" >&2
          return 2
        }
        podman_command="$(resolve_tool "''${FINITE_PODMAN:-}" podman)"
        syft_command="$(resolve_tool "''${FINITE_SYFT:-}" syft)"
        nix_store_command="$(resolve_tool "''${FINITE_NIX_STORE:-}" nix-store)"
        syft_store="''${FINITE_SYFT_STORE:-$(dirname "$(dirname "$(readlink -f "''${syft_command}")")")}"

        mapfile -t syft_closure < <(
          "''${nix_store_command}" --query --requisites "''${syft_store}"
        )
        syft_mounts=()
        for store_path in "''${syft_closure[@]}"; do
          syft_mounts+=(--volume "''${store_path}:''${store_path}:ro")
        done

        auth_args=()
        if [[ -n "''${REGISTRY_AUTH_FILE:-}" ]]; then
          auth_args+=(--authfile "''${REGISTRY_AUTH_FILE}")
        fi
        if [[ -n "''${SBOM_LOCAL_IMAGE:-}" ]]; then
          scan_image="''${SBOM_LOCAL_IMAGE}"
        else
          scan_image="$(''${podman_command} pull --quiet "''${auth_args[@]}" \
            "''${SBOM_IMAGE_REF}@''${SBOM_IMAGE_DIGEST}")"
        fi

        generated="$(mktemp "''${TMPDIR:-/tmp}/finite-sbom-generated.XXXXXX")"
        if ! "''${podman_command}" run --rm --pull=never \
          --cpus 4 \
          --env SYFT_CACHE_DIR=/tmp/syft-cache \
          --memory 4g \
          --network none \
          --security-opt label=disable \
          --user 0 \
          --volume "''${repo_root}/.github/syft.yaml:/run/finite-syft.yaml:ro" \
          "''${syft_mounts[@]}" \
          --entrypoint "''${syft_command}" \
          "''${scan_image}" \
          scan dir:/ \
            --config /run/finite-syft.yaml \
            --exclude './nix/store/**' \
            --source-name "''${SBOM_IMAGE_REF}" \
            --source-version "''${SBOM_IMAGE_DIGEST}" \
            --output spdx-json |
          jq -c '
            .packages |= map(
              if has("externalRefs") then
                .externalRefs |= map(
                  select(.referenceType != "cpe23Type")
                ) |
                if (.externalRefs | length) == 0 then
                  del(.externalRefs)
                else
                  .
                end
              else
                .
              end
            )
          ' >"''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        if ! validate_sbom "''${generated}"; then
          rm -f -- "''${generated}"
          return 1
        fi
        mv -- "''${generated}" "''${output}"
      }

      command="''${1:-}"
      [[ -n "''${command}" ]] || {
        usage
        exit 2
      }
      shift
      case "''${command}" in
        extract)
          (( $# == 1 )) || { usage; exit 2; }
          extract_attestation "$1"
          ;;
        generate)
          (( $# == 1 )) || { usage; exit 2; }
          generate_sbom "$1"
          ;;
        validate)
          (( $# == 1 )) || { usage; exit 2; }
          validate_sbom "$1"
          ;;
        equivalent)
          (( $# == 2 )) || { usage; exit 2; }
          equivalent_sboms "$1" "$2"
          ;;
        *) usage; exit 2 ;;
      esac
    '';
  };
}
