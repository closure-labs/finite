{
  homeCatalog,
  pkgs,
  foundation,
}: let
  catalog = homeCatalog;
  applications = foundation.lib.mkApplications {inherit pkgs;};
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
      echo "Seed generated; cloud-init is disabled by default on Finite. This ISO is inert unless an administrator explicitly enables full provisioning. Prefer importing profile.yaml with finite-home-init --profile." >&2
    '';
  };
in {
  inherit cloudInit;
  inherit (applications) homeBootstrap homeInit homeProfile homeUpdate homeMigrate;
}
