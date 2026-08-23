{
  generated,
  pkgs,
}: let
  catalog = "${generated}/bootc/generated/home-profile-catalog.json";
  runtimeInputs = with pkgs; [coreutils getent gnugrep jq yq-go];
  homeProfile = pkgs.writeShellApplication {
    name = "finite-home-profile";
    inherit runtimeInputs;
    text = ''
      foundation=""
      hardware=""
      roles=""
      format=""
      while (( $# > 0 )); do
        case "$1" in
          --foundation) foundation="''${2:?--foundation requires a value}"; shift 2 ;;
          --hardware) hardware="''${2:?--hardware requires a value}"; shift 2 ;;
          --roles) roles="''${2:?--roles requires a value}"; shift 2 ;;
          --format) format="''${2:?--format requires a value}"; shift 2 ;;
          *) echo "usage: finite-home-profile --foundation FOUNDATION --hardware HARDWARE --roles ROLE,... --format yaml" >&2; exit 2 ;;
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
        [[ "$foundation" == "$running_foundation" && "$hardware" == "$running_hardware" ]] || {
          echo "Requested $foundation/$hardware does not match running Finite foundation $running_foundation/$running_hardware" >&2
          exit 2
        }
      fi

      jq -n \
        --arg foundation "$foundation" \
        --arg hardware "$hardware" \
        --arg username "$username" \
        --arg home "$home_directory" \
        --argjson roles "$canonical" \
        '{schema: 1, foundation: $foundation, hardware: $hardware, roles: $roles, identity: {username: $username, homeDirectory: $home}}' |
        yq -P
    '';
  };
  homeBootstrap = pkgs.writeShellApplication {
    name = "finite-home-bootstrap";
    inherit runtimeInputs;
    text = ''
      profile_file=""
      legacy_file=""
      source_flake="github:closure-labs/finite"
      activate=true
      nix_command="''${FINITE_NIX_COMMAND:-nix}"
      while (( $# > 0 )); do
        case "$1" in
          --profile) profile_file="''${2:?--profile requires a value}"; shift 2 ;;
          --legacy-profile) legacy_file="''${2:?--legacy-profile requires a value}"; shift 2 ;;
          --source) source_flake="''${2:?--source requires a value}"; shift 2 ;;
          --check) activate=false; shift ;;
          *) echo "usage: finite-home-bootstrap (--profile YAML | --legacy-profile JSON) [--source FLAKE] [--check]" >&2; exit 2 ;;
        esac
      done
      [[ -n "$profile_file" && -z "$legacy_file" || -z "$profile_file" && -n "$legacy_file" ]] || {
        echo "Exactly one of --profile or --legacy-profile is required" >&2
        exit 2
      }
      [[ -n "$source_flake" && "$source_flake" != *$'\n'* ]] || { echo "Invalid --source" >&2; exit 2; }

      username=$(id -un)
      passwd_entry=$(getent passwd "$username")
      home_directory=$(cut -d: -f6 <<<"$passwd_entry")
      [[ "$username" =~ ^[a-z_][a-z0-9_-]*[$]?$ && "$home_directory" == /* ]] || {
        echo "Unable to discover a valid local account identity" >&2
        exit 2
      }

      config_parent="''${XDG_CONFIG_HOME:-$home_directory/.config}"
      install -d -m 0700 "$config_parent"
      workdir=$(mktemp -d "$config_parent/.finite-bootstrap.XXXXXX")
      trap 'rm -rf -- "$workdir"' EXIT
      if [[ -n "$profile_file" ]]; then
        yq -o=json '.' "$profile_file" >"$workdir/input.json" || {
          echo "Malformed YAML profile: $profile_file" >&2
          exit 2
        }
      else
        jq -e '
          type == "object" and
          ((.foundation // .baseClass) | type == "string") and
          (.hardware | type == "string") and
          ((.roles // []) | type == "array")
        ' "$legacy_file" >/dev/null || { echo "Malformed legacy profile: $legacy_file" >&2; exit 2; }
        jq '{schema: 1, foundation: (.foundation // .baseClass), hardware, roles: (.roles // []), identity: (.identity // {})}' \
          "$legacy_file" >"$workdir/input.json"
      fi

      jq -e '
        type == "object" and
        ((keys | sort) == ["foundation", "hardware", "identity", "roles", "schema"]) and
        .schema == 1 and
        (.foundation | type == "string") and
        (.hardware | type == "string") and
        (.roles | type == "array") and all(.roles[]; type == "string") and
        (.identity | type == "object") and
        ((.identity | keys) - ["homeDirectory", "username"] | length == 0)
      ' "$workdir/input.json" >/dev/null || { echo "Profile does not match schema 1" >&2; exit 2; }

      foundation=$(jq -er '.foundation' "$workdir/input.json")
      hardware=$(jq -er '.hardware' "$workdir/input.json")
      jq -e --arg foundation "$foundation" --arg hardware "$hardware" '
        .foundations[$foundation].hardware | index($hardware) != null
      ' ${catalog} >/dev/null || {
        echo "Unknown or incompatible foundation/hardware: $foundation/$hardware" >&2
        exit 2
      }
      roles=$(jq -c '.roles' "$workdir/input.json")
      [[ $(jq 'length' <<<"$roles") == $(jq 'unique | length' <<<"$roles") ]] || {
        echo "Duplicate roles are not allowed" >&2
        exit 2
      }
      jq -e --argjson roles "$roles" '. as $catalog | all($roles[]; $catalog.roles[.] != null)' ${catalog} >/dev/null || {
        echo "Profile contains an unknown role" >&2
        exit 2
      }
      canonical=$(jq -c --argjson requested "$roles" '
        [.roles | to_entries | sort_by(.value.order)[] | .key | select(. as $role | $requested | index($role) != null)]
      ' ${catalog})

      supplied_username=$(jq -r '.identity.username // empty' "$workdir/input.json")
      supplied_home=$(jq -r '.identity.homeDirectory // empty' "$workdir/input.json")
      [[ -z "$supplied_username" || "$supplied_username" == "$username" ]] || {
        echo "Profile identity username does not match the current account" >&2
        exit 2
      }
      [[ -z "$supplied_home" || "$supplied_home" == "$home_directory" ]] || {
        echo "Profile identity homeDirectory does not match the account database" >&2
        exit 2
      }

      running="''${FINITE_RUNNING_PROFILE_PATH:-/usr/share/finite/profile.json}"
      if [[ -r "$running" && "''${FINITE_SKIP_FOUNDATION_CHECK:-false}" != true ]]; then
        running_foundation=$(jq -er '.foundation' "$running")
        running_hardware=$(jq -er '.hardware' "$running")
        [[ "$foundation" == "$running_foundation" && "$hardware" == "$running_hardware" ]] || {
          echo "Profile $foundation/$hardware does not match running Finite foundation $running_foundation/$running_hardware" >&2
          exit 2
        }
      fi

      jq -n \
        --arg foundation "$foundation" --arg hardware "$hardware" \
        --arg username "$username" --arg home "$home_directory" \
        --argjson roles "$canonical" \
        '{schema: 1, foundation: $foundation, hardware: $hardware, roles: $roles, identity: {username: $username, homeDirectory: $home}}' \
        >"$workdir/profile.json"
      source_json=$(jq -Rn --arg value "$source_flake" '$value')
      {
        printf '%s\n' '{'
        printf '  inputs.finite.url = %s;\n' "$source_json"
        printf '%s\n' '  inputs.nixpkgs.follows = "finite/nixpkgs";'
        printf '%s\n' '  inputs.nixpkgs-weekly.follows = "finite/nixpkgs-weekly";'
        printf '%s\n' '  inputs.home-manager.follows = "finite/home-manager";'
        printf '%s\n' '  inputs.den.follows = "finite/den";'
        printf '%s\n' '  inputs.determinate.follows = "finite/determinate";'
        printf '%s\n' '  inputs.nix-flatpak.follows = "finite/nix-flatpak";'
        printf '%s\n' '  inputs.nixgl.follows = "finite/nixgl";'
        printf '%s\n' '  inputs.devenv.follows = "finite/devenv";'
        printf '%s\n' '  outputs = inputs@{ finite, nixpkgs, ... }:'
        printf '%s\n' '    (nixpkgs.lib.evalModules {'
        printf '%s\n' '      specialArgs = { inherit inputs; };'
        printf '%s\n' '      modules = ['
        printf '%s\n' '        finite.flakeModules.home'
        printf '%s\n' '        { finite.homeProfile = builtins.fromJSON (builtins.readFile ./profile.json); }'
        printf '%s\n' '      ];'
        printf '%s\n' '    }).config.flake;'
        printf '%s\n' '}'
      } >"$workdir/flake.nix"

      workflake="path:$workdir"
      "$nix_command" --accept-flake-config flake lock "$workflake"
      activation=$("$nix_command" --accept-flake-config build \
        "$workflake#homeConfigurations.finite.activationPackage" \
        --no-link --print-build-logs --print-out-paths)

      config_root="''${FINITE_BOOTSTRAP_CONFIG_ROOT:-$home_directory}"
      hm_dir="$config_root/.config/home-manager"
      finite_dir="$config_root/.config/finite"
      install -d -m 0700 "$hm_dir" "$finite_dir"
      for name in flake.nix flake.lock profile.json; do
        install -m 0600 "$workdir/$name" "$hm_dir/.$name.new"
        mv -f "$hm_dir/.$name.new" "$hm_dir/$name"
      done
      install -m 0600 "$workdir/profile.json" "$finite_dir/.profile.json.new"
      mv -f "$finite_dir/.profile.json.new" "$finite_dir/profile.json"
      printf 'Finite Home Manager configuration for %s builds as %s\n' "$username" "$activation"
      [[ "$activate" == false ]] || exec "$activation/activate"
    '';
  };
  cloudInit = pkgs.writeShellApplication {
    name = "finite-cloud-init";
    runtimeInputs = with pkgs; [coreutils jq xorriso yq-go];
    text = ''
      foundation="" hardware="" roles="" username="" output=""
      while (( $# > 0 )); do
        case "$1" in
          --foundation) foundation="''${2:?--foundation requires a value}"; shift 2 ;;
          --hardware) hardware="''${2:?--hardware requires a value}"; shift 2 ;;
          --roles) roles="''${2:?--roles requires a value}"; shift 2 ;;
          --user) username="''${2:?--user requires a value}"; shift 2 ;;
          --output) output="''${2:?--output requires a value}"; shift 2 ;;
          *) echo "usage: finite-cloud-init --foundation FOUNDATION --hardware HARDWARE --roles ROLE,... --user USER --output DIR" >&2; exit 2 ;;
        esac
      done
      [[ "$username" =~ ^[a-z_][a-z0-9_-]*[$]?$ && -n "$output" ]] || { echo "Valid --user and --output values are required" >&2; exit 2; }
      [[ ! -e "$output" ]] || { echo "Output already exists: $output" >&2; exit 2; }
      requested='[]'
      if [[ -n "$roles" ]]; then
        IFS=, read -ra role_list <<<"$roles"
        for role in "''${role_list[@]}"; do requested=$(jq -c --arg role "$role" '. + [$role]' <<<"$requested"); done
      fi
      jq -e --arg foundation "$foundation" --arg hardware "$hardware" --argjson roles "$requested" '
        (.foundations[$foundation].hardware | index($hardware) != null) and
        (. as $catalog | all($roles[]; $catalog.roles[.] != null)) and
        (($roles | unique | length) == ($roles | length))
      ' ${catalog} >/dev/null || { echo "Invalid Finite seed profile" >&2; exit 2; }
      canonical=$(jq -c --argjson requested "$requested" '[.roles | to_entries | sort_by(.value.order)[] | .key | select(. as $role | $requested | index($role) != null)]' ${catalog})
      profile=$(jq -n --arg foundation "$foundation" --arg hardware "$hardware" --arg username "$username" \
        --arg home "/var/home/$username" --argjson roles "$canonical" \
        '{schema: 1, foundation: $foundation, hardware: $hardware, roles: $roles, identity: {username: $username, homeDirectory: $home}}' | yq -P)
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
  inherit cloudInit homeBootstrap homeProfile;
}
