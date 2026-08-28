{
  generated,
  homeScaffold,
  pkgs,
}: let
  catalog = "${generated}/bootc/generated/home-profile-catalog.json";
  profileRuntimeInputs = with pkgs; [coreutils getent gnugrep jq yq-go];
  homeProfile = pkgs.writeShellApplication {
    name = "finite-home-profile";
    runtimeInputs = profileRuntimeInputs;
    text = ''
      foundation=""
      hardware=""
      packages=""
      roles=""
      format=""
      while (( $# > 0 )); do
        case "$1" in
          --foundation) foundation="''${2:?--foundation requires a value}"; shift 2 ;;
          --hardware) hardware="''${2:?--hardware requires a value}"; shift 2 ;;
          --packages) packages="''${2:?--packages requires a value}"; shift 2 ;;
          --roles) roles="''${2:?--roles requires a value}"; shift 2 ;;
          --format) format="''${2:?--format requires a value}"; shift 2 ;;
          *) echo "usage: finite-home-profile --foundation FOUNDATION --hardware HARDWARE --packages PACKAGE,... --roles ROLE,... --format yaml" >&2; exit 2 ;;
        esac
      done
      [[ "$format" == yaml ]] || { echo "--format must be yaml" >&2; exit 2; }
      jq -e --arg foundation "$foundation" --arg hardware "$hardware" '
        .foundations[$foundation].hardware | index($hardware) != null
      ' ${catalog} >/dev/null || {
        echo "Unknown or incompatible foundation/hardware: $foundation/$hardware" >&2
        exit 2
      }

      requested='[]'
      if [[ -n "$roles" ]]; then
        IFS=, read -ra role_list <<<"$roles"
        for role in "''${role_list[@]}"; do
          [[ "$role" =~ ^[a-z][a-z0-9-]*$ ]] || { echo "Invalid role: $role" >&2; exit 2; }
          jq -e --arg role "$role" '.roles[$role]' ${catalog} >/dev/null || {
            echo "Unknown role: $role" >&2
            exit 2
          }
          if jq -e --arg role "$role" 'index($role) != null' <<<"$requested" >/dev/null; then
            echo "Duplicate role: $role" >&2
            exit 2
          fi
          requested=$(jq -c --arg role "$role" '. + [$role]' <<<"$requested")
        done
      fi
      canonical=$(jq -c --argjson requested "$requested" '
        [.roles | to_entries | sort_by(.value.order)[] | .key | select(. as $role | $requested | index($role) != null)]
      ' ${catalog})
      requested_packages='[]'
      if [[ -n "$packages" ]]; then
        IFS=, read -ra package_list <<<"$packages"
        for package in "''${package_list[@]}"; do
          [[ "$package" =~ ^[a-z][a-z0-9-]*$ ]] || { echo "Invalid package: $package" >&2; exit 2; }
          jq -e --arg package "$package" '.packages[$package]' ${catalog} >/dev/null || {
            echo "Unknown package: $package" >&2
            exit 2
          }
          if jq -e --arg package "$package" 'index($package) != null' <<<"$requested_packages" >/dev/null; then
            echo "Duplicate package: $package" >&2
            exit 2
          fi
          requested_packages=$(jq -c --arg package "$package" '. + [$package]' <<<"$requested_packages")
        done
      fi
      canonical_packages=$(jq -c --argjson requested "$requested_packages" '
        [.packages | to_entries | sort_by(.value.order)[] | .key | select(. as $package | $requested | index($package) != null)]
      ' ${catalog})
      username=$(id -un)
      passwd_entry=$(getent passwd "$username")
      home_directory=$(cut -d: -f6 <<<"$passwd_entry")
      [[ "$username" =~ ^[a-z_][a-z0-9_-]*[$]?$ && "$home_directory" == /* ]] || {
        echo "Unable to discover a valid local account identity" >&2
        exit 2
      }

      running="''${FINITE_RUNNING_PROFILE_PATH:-/usr/share/finite/profile.json}"
      if [[ -r "$running" && "''${FINITE_SKIP_FOUNDATION_CHECK:-false}" != true ]]; then
        running_foundation=$(jq -er '.foundation' "$running")
        running_hardware=$(jq -er '.hardware' "$running")
        if [[ "$foundation" != "$running_foundation" ]] ||
          ! jq -e --arg hardware "$hardware" --arg image_hardware "$running_hardware" '
            .hardware[$hardware].imageHardware | index($image_hardware) != null
          ' ${catalog} >/dev/null; then
          echo "Requested $foundation/$hardware is incompatible with running Finite image $running_foundation/$running_hardware" >&2
          exit 2
        fi
      fi

      jq -n \
        --arg foundation "$foundation" \
        --arg hardware "$hardware" \
        --arg username "$username" \
        --arg home "$home_directory" \
        --argjson packages "$canonical_packages" \
        --argjson roles "$canonical" \
        '{schema: 2, foundation: $foundation, hardware: $hardware, packages: $packages, roles: $roles, identity: {username: $username, homeDirectory: $home}}' |
        yq -P
    '';
  };
  homeInitBody = pkgs.lib.removePrefix "#!/usr/bin/env bash\n" (
    builtins.readFile ../modules/aspects/base/rootfs/usr/libexec/finite/home-init
  );
  homeInit = pkgs.writeShellApplication {
    name = "finite-home-init";
    runtimeInputs = with pkgs; [coreutils findutils getent jq yq-go];
    text =
      ''
        export FINITE_HOME_TEMPLATE_PATH="''${FINITE_HOME_TEMPLATE_PATH:-${homeScaffold}}"
        export FINITE_HOME_CATALOG_PATH="''${FINITE_HOME_CATALOG_PATH:-${catalog}}"
      ''
      + homeInitBody;
  };
  # This is a command alias only. It intentionally implements no legacy
  # profile conversion or checkout-based source selection.
  homeBootstrap = pkgs.writeShellApplication {
    name = "finite-home-bootstrap";
    runtimeInputs = [homeInit];
    text = ''
      exec finite-home-init "$@"
    '';
  };
  cloudInit = pkgs.writeShellApplication {
    name = "finite-cloud-init";
    runtimeInputs = with pkgs; [coreutils jq xorriso yq-go];
    text = ''
      foundation="" hardware="" packages="" roles="" username="" output=""
      while (( $# > 0 )); do
        case "$1" in
          --foundation) foundation="''${2:?--foundation requires a value}"; shift 2 ;;
          --hardware) hardware="''${2:?--hardware requires a value}"; shift 2 ;;
          --packages) packages="''${2:?--packages requires a value}"; shift 2 ;;
          --roles) roles="''${2:?--roles requires a value}"; shift 2 ;;
          --user) username="''${2:?--user requires a value}"; shift 2 ;;
          --output) output="''${2:?--output requires a value}"; shift 2 ;;
          *) echo "usage: finite-cloud-init --foundation FOUNDATION --hardware HARDWARE --packages PACKAGE,... --roles ROLE,... --user USER --output DIR" >&2; exit 2 ;;
        esac
      done
      [[ "$username" =~ ^[a-z_][a-z0-9_-]*[$]?$ && -n "$output" ]] || { echo "Valid --user and --output values are required" >&2; exit 2; }
      [[ ! -e "$output" ]] || { echo "Output already exists: $output" >&2; exit 2; }
      requested='[]'
      if [[ -n "$roles" ]]; then
        IFS=, read -ra role_list <<<"$roles"
        for role in "''${role_list[@]}"; do requested=$(jq -c --arg role "$role" '. + [$role]' <<<"$requested"); done
      fi
      requested_packages='[]'
      if [[ -n "$packages" ]]; then
        IFS=, read -ra package_list <<<"$packages"
        for package in "''${package_list[@]}"; do requested_packages=$(jq -c --arg package "$package" '. + [$package]' <<<"$requested_packages"); done
      fi
      jq -e --arg foundation "$foundation" --arg hardware "$hardware" \
        --argjson packages "$requested_packages" --argjson roles "$requested" '
        (.foundations[$foundation].hardware | index($hardware) != null) and
        (. as $catalog | all($packages[]; $catalog.packages[.] != null)) and
        (($packages | unique | length) == ($packages | length)) and
        (. as $catalog | all($roles[]; $catalog.roles[.] != null)) and
        (($roles | unique | length) == ($roles | length))
      ' ${catalog} >/dev/null || { echo "Invalid Finite seed profile" >&2; exit 2; }
      canonical=$(jq -c --argjson requested "$requested" '[.roles | to_entries | sort_by(.value.order)[] | .key | select(. as $role | $requested | index($role) != null)]' ${catalog})
      canonical_packages=$(jq -c --argjson requested "$requested_packages" '[.packages | to_entries | sort_by(.value.order)[] | .key | select(. as $package | $requested | index($package) != null)]' ${catalog})
      profile=$(jq -n --arg foundation "$foundation" --arg hardware "$hardware" --arg username "$username" \
        --arg home "/var/home/$username" --argjson packages "$canonical_packages" --argjson roles "$canonical" \
        '{schema: 2, foundation: $foundation, hardware: $hardware, packages: $packages, roles: $roles, identity: {username: $username, homeDirectory: $home}}' | yq -P)
      workdir=$(mktemp -d)
      trap 'rm -rf -- "$workdir"' EXIT
      jq -n --arg path "/etc/finite/home-profiles/$username.yaml" --arg content "$profile" '
        {preserve_hostname: true, ssh_pwauth: false, write_files: [{path: $path, permissions: "0644", content: $content}]}
      ' | yq -P | { printf '#cloud-config\n'; cat; } >"$workdir/user-data"
      instance_hash=$(sha256sum "$workdir/user-data" | cut -c1-16)
      jq -n --arg id "finite-$instance_hash" '{"instance-id": $id, "local-hostname": "finite"}' | yq -P >"$workdir/meta-data"
      printf '%s\n' "$profile" >"$workdir/profile.yaml"
      xorriso -as mkisofs -quiet -V cidata -J -R -o "$workdir/seed.iso" "$workdir/user-data" "$workdir/meta-data"
      install -d "$output"
      install -m 0644 "$workdir/user-data" "$workdir/meta-data" "$workdir/profile.yaml" "$workdir/seed.iso" "$output/"
    '';
  };
in {
  inherit cloudInit homeBootstrap homeInit homeProfile;
}
