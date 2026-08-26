{
  bluefin,
  bluefinDx,
  determinateNix,
  pkgs,
}: let
  upstreamLocks = {
    inherit bluefin;
    bluefin-dx = bluefinDx;
  };
  upstreamLocksFile = pkgs.writeText "finite-upstreams.json" (builtins.toJSON upstreamLocks);
in rec {
  verifyBluefin = pkgs.writeShellApplication {
    name = "finite-verify-bluefin";
    runtimeInputs = [pkgs.cosign pkgs.jq];
    text = ''
      source_name="''${1:-bluefin}"
      jq -e --arg source "''${source_name}" '.[$source]' ${upstreamLocksFile} >/dev/null || {
        echo "Unknown Bluefin source: ''${source_name}" >&2
        exit 2
      }
      image="$(jq -er --arg source "''${source_name}" '.[$source].image + "@" + .[$source].digest' ${upstreamLocksFile})"
      issuer="$(jq -er --arg source "''${source_name}" '.[$source].cosign.issuer' ${upstreamLocksFile})"
      identity="$(jq -er --arg source "''${source_name}" '.[$source].cosign.identity' ${upstreamLocksFile})"
      cosign verify \
        --certificate-oidc-issuer "''${issuer}" \
        --certificate-identity "''${identity}" \
        "''${image}" >/dev/null
      printf '%s\n' "''${image}"
    '';
  };
  loadBluefin = pkgs.writeShellApplication {
    name = "finite-load-bluefin";
    runtimeInputs = with pkgs; [coreutils cosign jq skopeo];
    text = ''
      if [[ "''${CI:-}" == true && $EUID -ne 0 && -z "''${_FINITE_IN_USERNS:-}" ]]; then
        host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
        [[ -n "''${host_podman}" && "''${host_podman}" != /nix/store/* ]] || {
          echo "The CI runner's host Podman is required to enter rootless storage" >&2
          exit 1
        }
        exec env _FINITE_IN_USERNS=1 "''${host_podman}" unshare "$0" "$@"
      fi
      source_name="''${1:-bluefin}"
      ${verifyBluefin}/bin/finite-verify-bluefin "''${source_name}" >/dev/null
      locked_image="$(jq -er --arg source "''${source_name}" '.[$source].image' ${upstreamLocksFile})"
      locked_digest="$(jq -er --arg source "''${source_name}" '.[$source].digest' ${upstreamLocksFile})"
      locked_tag="$(jq -er --arg source "''${source_name}" '.[$source].tag' ${upstreamLocksFile})"
      locked_architecture="$(jq -er --arg source "''${source_name}" '.[$source].architecture' ${upstreamLocksFile})"
      source="docker://''${locked_image}@''${locked_digest}"
      image="''${locked_image}:''${locked_tag}"
      data_home="''${XDG_DATA_HOME:-''${HOME}/.local/share}"
      runtime_dir="''${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
      graph_root="''${CONTAINERS_STORAGE_GRAPHROOT:-''${data_home}/containers/storage}"
      run_root="''${CONTAINERS_STORAGE_RUNROOT:-''${runtime_dir}/containers}"
      storage_driver="''${CONTAINERS_STORAGE_DRIVER:-overlay}"
      storage_ref="containers-storage:[''${storage_driver}@''${graph_root}+''${run_root}]''${image}"
      install -d "''${graph_root}" "''${run_root}"
      loaded_digest="$(
        skopeo inspect --format '{{.Digest}}' "''${storage_ref}" 2>/dev/null || true
      )"
      if [[ "''${loaded_digest}" != "''${locked_digest}" ]]; then
        skopeo copy \
          --override-arch "''${locked_architecture}" \
          --override-os linux \
          --preserve-digests \
          --retry-times 3 \
          "''${source}" \
          "''${storage_ref}" >&2
        loaded_digest="$(
          skopeo inspect --format '{{.Digest}}' "''${storage_ref}"
        )"
      fi
      [[ "''${loaded_digest}" == "''${locked_digest}" ]] || {
        echo "Loaded Bluefin digest ''${loaded_digest} does not match ''${locked_digest}" >&2
        exit 1
      }
      printf '%s\n' "''${image}"
    '';
  };
  sourceVerify = pkgs.writeShellApplication {
    name = "finite-source-verify";
    runtimeInputs = with pkgs; [cosign coreutils curl skopeo];
    text = ''
      export FINITE_BLUEFIN_ARCHITECTURE=${bluefin.architecture}
      export FINITE_BLUEFIN_DIGEST=${bluefin.digest}
      export FINITE_BLUEFIN_IMAGE=${bluefin.image}
      export FINITE_BLUEFIN_ISSUER=${bluefin.cosign.issuer}
      export FINITE_BLUEFIN_IDENTITY=${bluefin.cosign.identity}
      export FINITE_DETERMINATE_NIX_INSTALLER_SHA256=${determinateNix.installer.sha256}
      export FINITE_DETERMINATE_NIX_INSTALLER_URL=${pkgs.lib.escapeShellArg determinateNix.installer.url}
      export FINITE_DETERMINATE_NIX_POLICY_SHA256=${determinateNix.selinuxPolicy.sha256}
      export FINITE_DETERMINATE_NIX_POLICY_URL=${pkgs.lib.escapeShellArg determinateNix.selinuxPolicy.url}
      export FINITE_DETERMINATE_NIX_FC_SHA256=${determinateNix.selinuxFileContexts.sha256}
      export FINITE_DETERMINATE_NIX_FC_URL=${pkgs.lib.escapeShellArg determinateNix.selinuxFileContexts.url}
      export FINITE_DETERMINATE_NIX_VERSION=${determinateNix.version}
      source_name="''${1:?usage: finite-source-verify SOURCE}"
      case "''${source_name}" in
        bluefin | bluefin-dx)
          image="$(jq -er --arg source "''${source_name}" '.[$source].image' ${upstreamLocksFile})"
          architecture="$(jq -er --arg source "''${source_name}" '.[$source].architecture' ${upstreamLocksFile})"
          digest="$(jq -er --arg source "''${source_name}" '.[$source].digest' ${upstreamLocksFile})"
          issuer="$(jq -er --arg source "''${source_name}" '.[$source].cosign.issuer' ${upstreamLocksFile})"
          identity="$(jq -er --arg source "''${source_name}" '.[$source].cosign.identity' ${upstreamLocksFile})"
          skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
            "docker://''${image}@''${digest}" >/dev/null
          cosign verify \
            --certificate-oidc-issuer "''${issuer}" \
            --certificate-identity "''${identity}" \
            "''${image}@''${digest}" >/dev/null
          ;;
        determinate-nix)
          installer="$(mktemp)"
          policy="$(mktemp)"
          file_contexts="$(mktemp)"
          trap 'rm -f -- "''${installer}" "''${policy}" "''${file_contexts}"' EXIT
          curl --fail --location --retry 3 --output "''${installer}" \
            "''${FINITE_DETERMINATE_NIX_INSTALLER_URL:?}"
          curl --fail --location --retry 3 --output "''${policy}" \
            "''${FINITE_DETERMINATE_NIX_POLICY_URL:?}"
          curl --fail --location --retry 3 --output "''${file_contexts}" \
            "''${FINITE_DETERMINATE_NIX_FC_URL:?}"
          printf '%s  %s\n' "''${FINITE_DETERMINATE_NIX_INSTALLER_SHA256:?}" "''${installer}" |
            sha256sum --check --status
          printf '%s  %s\n' "''${FINITE_DETERMINATE_NIX_POLICY_SHA256:?}" "''${policy}" |
            sha256sum --check --status
          printf '%s  %s\n' "''${FINITE_DETERMINATE_NIX_FC_SHA256:?}" "''${file_contexts}" |
            sha256sum --check --status
          printf 'determinate-nix@%s\n' "''${FINITE_DETERMINATE_NIX_VERSION:?}"
          exit 0
          ;;
        *)
          echo "Unknown OCI source: ''${source_name}" >&2
          exit 2
          ;;
      esac
      printf '%s@%s\n' "''${image}" "''${digest}"
    '';
  };
  sourceUpdate = pkgs.writeShellApplication {
    name = "finite-source-update";
    runtimeInputs = with pkgs; [coreutils cosign curl diffutils gh jq skopeo];
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
        bluefin | bluefin-dx)
          lock="''${repo_root}/sources/''${source_name}.json"
          [[ -f "''${lock}" ]]
          image="$(jq -er '.image' "''${lock}")"
          tag="$(jq -er '.tag' "''${lock}")"
          architecture="$(jq -er '.architecture' "''${lock}")"
          current="$(jq -er '.digest' "''${lock}")"
          digest="$(
            skopeo inspect --retry-times 3 --override-arch "''${architecture}" \
              --format '{{.Digest}}' "docker://''${image}:''${tag}"
          )"
          [[ "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]
          if [[ "''${source_name}" == bluefin || "''${source_name}" == bluefin-dx ]]; then
            issuer="$(jq -er '.cosign.issuer' "''${lock}")"
            identity="$(jq -er '.cosign.identity' "''${lock}")"
            cosign verify \
              --certificate-oidc-issuer "''${issuer}" \
              --certificate-identity "''${identity}" \
              "''${image}@''${digest}" >/dev/null
          fi
          changed=false
          if [[ "''${current}" != "''${digest}" ]]; then
            temporary="$(mktemp "''${lock}.XXXXXX")"
            trap 'rm -f -- "''${temporary}"' EXIT
            jq --arg digest "''${digest}" '.digest = $digest' "''${lock}" >"''${temporary}"
            chmod --reference="''${lock}" "''${temporary}"
            mv -- "''${temporary}" "''${lock}"
            changed=true
          fi
          ;;
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
  };
}
