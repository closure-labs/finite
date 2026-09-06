{
  pkgs,
  policy,
}:
pkgs.writeShellApplication {
  name = "finite-repository-security-audit";
  runtimeInputs = with pkgs; [coreutils diffutils gh jq];
  text = ''
    set -euo pipefail

    usage() {
      cat >&2 <<'EOF'
    usage: finite-repository-security-audit [--policy FILE] [--repository OWNER/REPO]
                                              [--snapshot FILE]
    EOF
    }

    policy_file=${policy}
    repository="''${GH_REPOSITORY:-}"
    snapshot=
    while (($#)); do
      case "$1" in
        --policy)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          policy_file=$2
          shift 2
          ;;
        --repository)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          repository=$2
          shift 2
          ;;
        --snapshot)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          snapshot=$2
          shift 2
          ;;
        -h | --help)
          usage
          exit 0
          ;;
        *)
          usage
          exit 2
          ;;
      esac
    done

    emit_invalid() {
      local message=$1
      printf '%s\n' "$message" >&2
      jq -cn --arg repository "''${repository:-unknown}" '{
        schema: 1,
        repository: $repository,
        status: "invalid",
        drift: []
      }'
      exit 2
    }

    [[ -r "''${policy_file}" ]] || emit_invalid "Repository security policy is unreadable: ''${policy_file}"
    policy_json="$(jq -ce . "''${policy_file}" 2>/dev/null)" ||
      emit_invalid "Repository security policy is not valid JSON: ''${policy_file}"
    jq -e '
      .schema == 1 and
      (.repository | test("^[^/]+/[^/]+$")) and
      .actions.allowed_actions == "selected" and
      .actions.sha_pinning_required == true and
      .actions.selected_actions.github_owned_allowed == true and
      .actions.selected_actions.verified_allowed == false and
      .actions.workflow_permissions.default_workflow_permissions == "read" and
      .actions.workflow_permissions.can_approve_pull_request_reviews == false and
      .security.vulnerability_alerts == true and
      .security.dependabot_security_updates == true and
      .security.secret_scanning == true and
      .security.secret_scanning_push_protection == true and
      .environments == {}
    ' <<<"''${policy_json}" >/dev/null || emit_invalid "Repository security policy violates the Finite schema"

    policy_repository="$(jq -r '.repository' <<<"''${policy_json}")"
    repository="''${repository:-''${policy_repository}}"
    [[ "''${repository}" == "''${policy_repository}" ]] ||
      emit_invalid "Requested repository does not match policy: ''${repository}"

    if [[ -n "''${snapshot}" ]]; then
      [[ -r "''${snapshot}" ]] || emit_invalid "Repository snapshot is unreadable: ''${snapshot}"
      actual_json="$(jq -ce . "''${snapshot}" 2>/dev/null)" ||
        emit_invalid "Repository snapshot is not valid JSON: ''${snapshot}"
    else
      actions_json="$(gh api "repos/''${repository}/actions/permissions")"
      if [[ "$(jq -r '.allowed_actions' <<<"''${actions_json}")" == selected ]]; then
        selected_json="$(gh api "repos/''${repository}/actions/permissions/selected-actions")"
      else
        selected_json='{"github_owned_allowed":false,"verified_allowed":false,"patterns_allowed":[]}'
      fi
      workflow_json="$(gh api "repos/''${repository}/actions/permissions/workflow")"
      repository_json="$(gh api "repos/''${repository}")"
      dependabot_json="$(gh api "repos/''${repository}/automated-security-fixes")"
      vulnerability_alerts=false
      if gh api --silent "repos/''${repository}/vulnerability-alerts" 2>/dev/null; then
        vulnerability_alerts=true
      fi

      environment_json='{}'

      actual_json="$(
        jq -cn \
          --arg repository "''${repository}" \
          --argjson actions "''${actions_json}" \
          --argjson selected "''${selected_json}" \
          --argjson workflow "''${workflow_json}" \
          --argjson metadata "''${repository_json}" \
          --argjson dependabot "''${dependabot_json}" \
          --argjson vulnerability_alerts "''${vulnerability_alerts}" \
          --argjson environments "''${environment_json}" '
            {
              schema: 1,
              repository: $repository,
              actions: {
                enabled: $actions.enabled,
                allowed_actions: $actions.allowed_actions,
                sha_pinning_required: $actions.sha_pinning_required,
                selected_actions: {
                  github_owned_allowed: $selected.github_owned_allowed,
                  verified_allowed: $selected.verified_allowed,
                  patterns_allowed: ($selected.patterns_allowed | sort)
                },
                workflow_permissions: {
                  default_workflow_permissions: $workflow.default_workflow_permissions,
                  can_approve_pull_request_reviews: $workflow.can_approve_pull_request_reviews
                }
              },
              security: {
                vulnerability_alerts: $vulnerability_alerts,
                dependabot_security_updates: ($dependabot.enabled // false),
                secret_scanning:
                  ($metadata.security_and_analysis.secret_scanning.status == "enabled"),
                secret_scanning_push_protection:
                  ($metadata.security_and_analysis.secret_scanning_push_protection.status == "enabled")
              },
              environments: $environments
            }
          '
      )"
    fi

    actual_json="$(jq -cS . <<<"''${actual_json}" 2>/dev/null)" ||
      emit_invalid "Repository security snapshot does not match the expected JSON shape"
    expected_json="$(jq -cS . <<<"''${policy_json}")"
    drift="$(
      jq -cn \
        --argjson expected "''${expected_json}" \
        --argjson actual "''${actual_json}" '
          [($expected | paths) as $path |
            ($expected | getpath($path)) as $value |
            select(($value | type) != "object") |
            select($value != ($actual | getpath($path))) |
            ($path | map(tostring) | join("."))] |
          unique | sort
        '
    )"

    if [[ "''${drift}" != '[]' ]]; then
      diff -u \
        <(jq -S . <<<"''${expected_json}") \
        <(jq -S . <<<"''${actual_json}") >&2 || true
      jq -cn \
        --arg repository "''${repository}" \
        --argjson drift "''${drift}" '{
          schema: 1,
          repository: $repository,
          status: "drift",
          drift: $drift
        }'
      exit 1
    fi

    jq -cn --arg repository "''${repository}" '{
      schema: 1,
      repository: $repository,
      status: "pass",
      drift: []
    }'
  '';
}
