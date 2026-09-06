{pkgs}:
pkgs.writeShellApplication {
  name = "finite-source-update";
  runtimeInputs = with pkgs; [coreutils curl diffutils gh jq];
  text = ''
    repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
    [[ -f "''${repo_root}/flake.nix" ]] || {
      echo "Run this command from the Finite repository root" >&2
      exit 2
    }
    cd "''${repo_root}" || exit
    source_name="''${1:?usage: finite-source-update SOURCE [OUTPUT_FILE]}"
    output_file="''${2:-}"
    case "''${source_name}" in
      determinate-nix)
        lock="''${repo_root}/sources/determinate-nix.json"
        [[ -f "''${lock}" ]]
        release="$(gh api repos/DeterminateSystems/nix-installer/releases/latest)"
        jq -e '.draft == false and .prerelease == false' <<<"''${release}" >/dev/null
        tag="$(jq -er '.tag_name | select(test("^v[0-9]+\\.[0-9]+\\.[0-9]+$"))' <<<"''${release}")"
        version="''${tag#v}"
        asset="$(jq -ec '.assets[] | select(.name == "nix-installer-x86_64-linux")' <<<"''${release}")"
        installer_url="$(jq -er .browser_download_url <<<"''${asset}")"
        digest="$(jq -er '.digest | select(test("^sha256:[0-9a-f]{64}$"))' <<<"''${asset}")"
        installer_sha256="''${digest#sha256:}"
        policy_url="https://raw.githubusercontent.com/DeterminateSystems/nix-installer/''${tag}/src/action/linux/selinux/determinate-nix.pp"
        file_contexts_url="https://raw.githubusercontent.com/DeterminateSystems/nix-installer/''${tag}/src/action/linux/selinux/nix.fc"
        policy_file="$(mktemp)"
        file_contexts_file="$(mktemp)"
        temporary="$(mktemp "''${lock}.XXXXXX")"
        trap 'rm -f -- "''${policy_file}" "''${file_contexts_file}" "''${temporary}"' EXIT
        curl --fail --location --retry 3 --output "''${policy_file}" "''${policy_url}"
        curl --fail --location --retry 3 --output "''${file_contexts_file}" "''${file_contexts_url}"
        policy_sha256="$(sha256sum "''${policy_file}" | cut -d' ' -f1)"
        file_contexts_sha256="$(sha256sum "''${file_contexts_file}" | cut -d' ' -f1)"
        jq \
          --arg version "''${version}" \
          --arg installer_url "''${installer_url}" \
          --arg installer_sha256 "''${installer_sha256}" \
          --arg policy_url "''${policy_url}" \
          --arg policy_sha256 "''${policy_sha256}" \
          --arg file_contexts_url "''${file_contexts_url}" \
          --arg file_contexts_sha256 "''${file_contexts_sha256}" '
            .version = $version |
            .installer.url = $installer_url |
            .installer.sha256 = $installer_sha256 |
            .selinuxPolicy.url = $policy_url |
            .selinuxPolicy.sha256 = $policy_sha256 |
            .selinuxFileContexts.url = $file_contexts_url |
            .selinuxFileContexts.sha256 = $file_contexts_sha256
          ' "''${lock}" >"''${temporary}"
        changed=false
        if ! cmp --silent "''${lock}" "''${temporary}"; then
          chmod --reference="''${lock}" "''${temporary}"
          mv -- "''${temporary}" "''${lock}"
          changed=true
        fi
        ;;
      *)
        echo "Unknown source: ''${source_name}" >&2
        exit 2
        ;;
    esac
    if [[ -n "''${output_file}" ]]; then
      {
        printf 'changed=%s\n' "''${changed}"
        printf 'digest=%s\n' "''${digest}"
      } >>"''${output_file}"
    else
      jq -cn --arg source "''${source_name}" --arg digest "''${digest}" \
        --argjson changed "''${changed}" \
        '{source: $source, changed: $changed, digest: $digest}'
    fi
  '';
}
