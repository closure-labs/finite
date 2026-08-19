{pkgs}:
pkgs.writeShellApplication {
  name = "purplefin-ci-gate";
  runtimeInputs = [pkgs.coreutils];
  text = ''
    set -euo pipefail

    require_result() {
      local job=$1 actual=$2 expected=$3
      if [[ "''${actual}" != "''${expected}" ]]; then
        printf '%s finished with %s; expected %s\n' \
          "''${job}" "''${actual}" "''${expected}" >&2
        return 1
      fi
    }

    require_selected_result() {
      local job=$1 selected=$2 actual=$3
      if [[ "''${selected}" == true ]]; then
        require_result "''${job}" "''${actual}" success
      else
        require_result "''${job}" "''${actual}" skipped
      fi
    }

    require_result prepare "''${PREPARE_RESULT:?}" success

    if [[ "''${EVENT_NAME:?}" == pull_request || "''${EVENT_NAME}" == merge_group || "''${VALIDATE_ONLY:-false}" == true ]]; then
      require_selected_result build-candidate "''${HAS_BUILDS:-false}" "''${BUILD_CANDIDATE_RESULT:?}"
      require_selected_result installer-candidate "''${INSTALLER_SELECTED:?}" "''${INSTALLER_CANDIDATE_RESULT:?}"
      require_result base-publish "''${BASE_PUBLISH_RESULT:?}" skipped
      require_result hardware-publish "''${HARDWARE_PUBLISH_RESULT:?}" skipped
      require_result roles-publish "''${ROLES_PUBLISH_RESULT:?}" skipped
      require_result base-sbom "''${BASE_SBOM_RESULT:?}" skipped
      require_result hardware-sbom "''${HARDWARE_SBOM_RESULT:?}" skipped
      require_result role-sbom "''${ROLE_SBOM_RESULT:?}" skipped
      require_result promote "''${PROMOTE_RESULT:?}" skipped
      exit 0
    fi

    require_result build-candidate "''${BUILD_CANDIDATE_RESULT:?}" skipped
    require_result installer-candidate "''${INSTALLER_CANDIDATE_RESULT:?}" skipped
    if [[ "''${EVENT_NAME}" == workflow_dispatch && "''${REF:?}" != refs/heads/main ]]; then
      echo 'Publishing workflow dispatches must target main' >&2
      exit 1
    fi
    require_selected_result base-publish "''${HAS_ROOT_BASE:-false}" "''${BASE_PUBLISH_RESULT:?}"
    require_selected_result hardware-publish "''${HAS_HARDWARE:-false}" "''${HARDWARE_PUBLISH_RESULT:?}"
    require_selected_result roles-publish "''${HAS_ROLES:-false}" "''${ROLES_PUBLISH_RESULT:?}"
    require_selected_result base-sbom "''${HAS_BASE_SBOM:-false}" "''${BASE_SBOM_RESULT:?}"
    require_selected_result hardware-sbom "''${HAS_HARDWARE_SBOM:-false}" "''${HARDWARE_SBOM_RESULT:?}"
    require_selected_result role-sbom "''${HAS_ROLE_SBOM:-false}" "''${ROLE_SBOM_RESULT:?}"
    require_selected_result promote "''${HAS_BUILDS:-false}" "''${PROMOTE_RESULT:?}"
  '';
}
