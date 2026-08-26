{pkgs}:
pkgs.writeShellApplication {
  name = "finite-github-output";
  runtimeInputs = with pkgs; [coreutils jq];
  text = ''
    set -euo pipefail

    report="''${1:?usage: finite-github-output REPORT.json}"
    : "''${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
    [[ -r "''${report}" ]] || {
      echo "Machine report is unreadable: ''${report}" >&2
      exit 2
    }

    normalized="$(jq -ceS '
      if type == "object" and
        .schema == 1 and
        all(keys[]; test("^[a-z][a-z0-9_]*$")) and
        all(to_entries[];
          (.value | type) == "string" or
          (.value | type) == "number" or
          (.value | type) == "boolean")
      then .
      else error("report must contain only schema 1 and validated scalar fields")
      end
    ' "''${report}")" || {
      echo "Machine report does not satisfy the GitHub output schema" >&2
      exit 2
    }

    while IFS=$'\t' read -r key value; do
      [[ "''${key}" == schema ]] && continue
      [[ "''${value}" != *$'\n'* && "''${value}" != *$'\r'* ]] || {
        echo "GitHub output contains a line break: ''${key}" >&2
        exit 2
      }
      printf '%s=%s\n' "''${key}" "''${value}" >>"''${GITHUB_OUTPUT}"
    done < <(jq -r 'to_entries[] | [.key, (.value | tostring)] | @tsv' <<<"''${normalized}")

    printf '%s\n' "''${normalized}"
  '';
}
