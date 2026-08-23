{
  pkgs,
  validateCiPlan,
}:
pkgs.writeShellApplication {
  name = "finite-ci-gate";
  runtimeInputs = with pkgs; [coreutils jq validateCiPlan];
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
    lifecycle="''${CI_PLAN:?CI_PLAN is required}"
    plan_file="$(mktemp "''${TMPDIR:-/tmp}/finite-ci-gate-plan.XXXXXX.json")"
    trap 'rm -f -- "''${plan_file}"' EXIT
    printf '%s\n' "''${lifecycle}" >"''${plan_file}"
    finite-ci-validate-plan "''${plan_file}"
    has_root_base="$(jq -r '.publication.builds.root' <<<"''${lifecycle}")"
    has_hardware="$(jq -r '.publication.builds.hardware' <<<"''${lifecycle}")"
    has_roles="$(jq -r '.publication.builds.roles' <<<"''${lifecycle}")"
    has_base_sbom="$(jq -r '.publication.sbom.base' <<<"''${lifecycle}")"
    has_hardware_sbom="$(jq -r '.publication.sbom.hardware' <<<"''${lifecycle}")"
    has_role_sbom="$(jq -r '.publication.sbom.roles' <<<"''${lifecycle}")"
    installer_selected="$(jq -r '.validation.installer.required' <<<"''${lifecycle}")"
    validation_images="$(jq -r '.validation.images.required' <<<"''${lifecycle}")"
    promote_selected="$(jq -r '.publication.promote' <<<"''${lifecycle}")"

    if [[ "''${EVENT_NAME:?}" == pull_request || "''${EVENT_NAME}" == merge_group || "''${VALIDATE_ONLY:-false}" == true ]]; then
      require_selected_result build-candidate "''${validation_images}" "''${BUILD_CANDIDATE_RESULT:?}"
      require_selected_result installer-candidate "''${installer_selected}" "''${INSTALLER_CANDIDATE_RESULT:?}"
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
    require_selected_result base-publish "''${has_root_base}" "''${BASE_PUBLISH_RESULT:?}"
    require_selected_result hardware-publish "''${has_hardware}" "''${HARDWARE_PUBLISH_RESULT:?}"
    require_selected_result roles-publish "''${has_roles}" "''${ROLES_PUBLISH_RESULT:?}"
    require_selected_result base-sbom "''${has_base_sbom}" "''${BASE_SBOM_RESULT:?}"
    require_selected_result hardware-sbom "''${has_hardware_sbom}" "''${HARDWARE_SBOM_RESULT:?}"
    require_selected_result role-sbom "''${has_role_sbom}" "''${ROLE_SBOM_RESULT:?}"
    require_selected_result promote "''${promote_selected}" "''${PROMOTE_RESULT:?}"
  '';
}
