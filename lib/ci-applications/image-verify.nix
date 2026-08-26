{pkgs}:
pkgs.writeShellApplication {
  name = "finite-image-verify";
  runtimeInputs = with pkgs; [coreutils cosign gh jq skopeo];
  text = ''
    set -euo pipefail

    usage() {
      cat >&2 <<'EOF'
    usage: finite-image-verify --image IMAGE --digest sha256:DIGEST
             --cosign-identity IDENTITY [--source-sha SHA]
             [--provenance-workflow WORKFLOW] [--sbom-workflow WORKFLOW]
             [--expect-label KEY=VALUE]... [--attempts COUNT]
    EOF
    }

    image=
    digest=
    identity=
    source_sha=
    provenance_workflow=
    sbom_workflow=
    attempts=6
    expected_labels='{}'
    while (($#)); do
      case "$1" in
        --image) image="''${2:-}"; shift 2 ;;
        --digest) digest="''${2:-}"; shift 2 ;;
        --cosign-identity) identity="''${2:-}"; shift 2 ;;
        --source-sha) source_sha="''${2:-}"; shift 2 ;;
        --provenance-workflow) provenance_workflow="''${2:-}"; shift 2 ;;
        --sbom-workflow) sbom_workflow="''${2:-}"; shift 2 ;;
        --attempts) attempts="''${2:-}"; shift 2 ;;
        --expect-label)
          label="''${2:-}"
          [[ "''${label}" == *=* && "''${label%%=*}" =~ ^[A-Za-z0-9._-]+$ ]] || {
            echo "Invalid expected label: ''${label}" >&2
            exit 2
          }
          expected_labels="$(jq -c \
            --arg key "''${label%%=*}" \
            --arg value "''${label#*=}" \
            '. + {($key): $value}' <<<"''${expected_labels}")"
          shift 2
          ;;
        -h | --help) usage; exit 0 ;;
        *) usage; exit 2 ;;
      esac
    done

    [[ -n "''${image}" && -n "''${identity}" ]] || { usage; exit 2; }
    [[ "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
      echo "Invalid image digest: ''${digest}" >&2
      exit 2
    }
    [[ "''${attempts}" =~ ^[1-9][0-9]*$ ]] || {
      echo "Attestation attempts must be a positive integer" >&2
      exit 2
    }
    if [[ -n "''${source_sha}" && ! "''${source_sha}" =~ ^[0-9a-f]{40}$ ]]; then
      echo "Invalid source SHA: ''${source_sha}" >&2
      exit 2
    fi
    if [[ -n "''${provenance_workflow}" || -n "''${sbom_workflow}" ]]; then
      : "''${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required for attestation verification}"
      [[ -n "''${source_sha}" ]] || {
        echo "A source SHA is required for attestation verification" >&2
        exit 2
      }
    fi

    skopeo_command="''${FINITE_SKOPEO:-skopeo}"
    cosign_command="''${FINITE_COSIGN:-cosign}"
    gh_command="''${FINITE_GH:-gh}"
    immutable_ref="''${image}@''${digest}"
    metadata="$("''${skopeo_command}" inspect --retry-times 3 "docker://''${immutable_ref}")"
    actual_digest="$(jq -er '.Digest' <<<"''${metadata}")"
    [[ "''${actual_digest}" == "''${digest}" ]] || {
      echo "Resolved digest ''${actual_digest} does not match ''${digest}" >&2
      exit 1
    }
    jq -e --argjson expected "''${expected_labels}" '
      (.Labels // {}) as $actual |
      $expected | to_entries | all(.[]; $actual[.key] == .value)
    ' <<<"''${metadata}" >/dev/null || {
      echo "Image labels do not match the requested contract" >&2
      exit 1
    }

    "''${cosign_command}" verify \
      --certificate-oidc-issuer https://token.actions.githubusercontent.com \
      --certificate-identity "''${identity}" \
      "''${immutable_ref}" >/dev/null || {
      echo "Image signer identity verification failed" >&2
      exit 1
    }

    verify_attestation() {
      local workflow=$1
      local predicate=$2
      local count=0
      while ((count < attempts)); do
        count=$((count + 1))
        if "''${gh_command}" attestation verify "oci://''${immutable_ref}" \
          --bundle-from-oci \
          --repo "''${GITHUB_REPOSITORY}" \
          --signer-workflow "''${workflow}" \
          --source-digest "''${source_sha}" \
          --predicate-type "''${predicate}" >/dev/null 2>&1; then
          printf '%s\n' "''${count}"
          return 0
        fi
        if ((count < attempts)); then
          sleep "''${FINITE_ATTESTATION_RETRY_DELAY:-5}"
        fi
      done
      echo "Attestation verification failed for ''${workflow}" >&2
      return 1
    }

    provenance_attempts=0
    sbom_attempts=0
    if [[ -n "''${provenance_workflow}" ]]; then
      provenance_attempts="$(verify_attestation \
        "''${provenance_workflow}" https://slsa.dev/provenance/v1)"
    fi
    if [[ -n "''${sbom_workflow}" ]]; then
      sbom_attempts="$(verify_attestation \
        "''${sbom_workflow}" https://spdx.dev/Document/v2.3)"
    fi

    jq -cn \
      --arg digest "''${digest}" \
      --arg image "''${image}" \
      --argjson labels_verified true \
      --argjson cosign_verified true \
      --argjson provenance_attempts "''${provenance_attempts}" \
      --argjson sbom_attempts "''${sbom_attempts}" '{
        schema: 1,
        image: $image,
        digest: $digest,
        labels_verified: $labels_verified,
        cosign_verified: $cosign_verified,
        provenance_attempts: $provenance_attempts,
        sbom_attempts: $sbom_attempts
      }'
  '';
}
