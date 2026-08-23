{
  generated,
  loadBluefin,
  pkgs,
  rechunkImage,
  version,
}:
pkgs.writeShellApplication {
  name = "finite-validate-image-shard";
  runtimeInputs = with pkgs; [coreutils jq skopeo];
  text = ''
       export FINITE_GENERATED_ROOT=${generated}
       export FINITE_LOAD_BLUEFIN=${loadBluefin}/bin/finite-load-bluefin
       export FINITE_RECHUNK_IMAGE=${rechunkImage}/bin/finite-rechunk-image
       export FINITE_VERSION=${version}
       export FINITE_DEFAULT_BUILDAH=${pkgs.buildah}/bin/buildah
       export FINITE_DEFAULT_PODMAN=${pkgs.podman}/bin/podman
       set -euo pipefail

       if [[ "''${CI:-}" == true ]]; then
         host_buildah="$(PATH=/usr/local/bin:/usr/bin:/bin command -v buildah || true)"
         host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
         [[ -n "''${host_buildah}" && -n "''${host_podman}" ]] || {
           echo "The CI runner's host Buildah and Podman are required" >&2
           exit 1
         }
         export FINITE_BUILDAH="''${host_buildah}"
         export FINITE_PODMAN="''${host_podman}"
       else
         export FINITE_BUILDAH="''${FINITE_DEFAULT_BUILDAH:?FINITE_DEFAULT_BUILDAH is required}"
         export FINITE_PODMAN="''${FINITE_DEFAULT_PODMAN:?FINITE_DEFAULT_PODMAN is required}"
       fi
       repo_root="''${FINITE_SOURCE_ROOT:-$PWD}"
       cd "''${repo_root}" || exit
       : "''${FINITE_GENERATED_ROOT:?FINITE_GENERATED_ROOT is required}"
       : "''${FINITE_LOAD_BLUEFIN:?FINITE_LOAD_BLUEFIN is required}"
       : "''${FINITE_RECHUNK_IMAGE:?FINITE_RECHUNK_IMAGE is required}"
       : "''${FINITE_VERSION:?FINITE_VERSION is required}"

       profile_matrix="''${FINITE_GENERATED_ROOT}/bootc/generated/image-matrix.json"
       profile_shard="''${PROFILE_SHARD:?PROFILE_SHARD is required}"

       usage() {
         echo "usage: finite-validate-image-shard [--check]" >&2
       }

       declare -A validated_images=()
       retained_images=()
       cleanup_shard() {
         status=$?
         set +e
         for image in "''${retained_images[@]:-}"; do
           [[ -z "''${image}" ]] || "''${FINITE_PODMAN:-podman}" image rm --force "''${image}" >/dev/null 2>&1
         done
         exit "''${status}"
       }
       trap cleanup_shard EXIT

       validate_contract() {
         jq -e '
           type == "array" and length > 0 and
           all(.[];
             type == "object" and
             (.profile | type == "string" and length > 0) and
             (.build_input | type == "string" and test("^[0-9a-f]{64}$")) and
             (.foundation == "bluefin" or .foundation == "bluefin-dx") and
             (.hardware == "generic-x86_64" or .hardware == "dell-xps-9350-intel") and
             (.tags | type == "string" and length > 0) and
             (.upstream.image | type == "string" and length > 0) and
             (.upstream.digest | type == "string" and test("^sha256:[0-9a-f]{64}$")) and
             (.target | type == "boolean") and
             (.stage == "root" or .stage == "hardware" or .stage == "role")
           ) and
           ([.[].profile] | length) == ([.[].profile] | unique | length)
         ' <<<"''${profile_shard}" >/dev/null || {
           echo "PROFILE_SHARD must contain unique, valid profile entries" >&2
           return 2
         }

         while IFS= read -r entry; do
           profile="$(jq -er '.profile' <<<"''${entry}")"
           expected="$(jq -cer --arg profile "''${profile}" '
             .[] | select(.profile == $profile) |
             {profile, build_input, foundation, hardware, tags, stage, parent, upstream}
           ' "''${profile_matrix}")" || {
             echo "Unknown profile in shard: ''${profile}" >&2
             return 2
           }
           actual="$(jq -c '{profile, build_input, foundation, hardware, tags, stage, parent, upstream}' <<<"''${entry}")"
           [[ "''${actual}" == "''${expected}" ]] || {
             echo "Shard contract for ''${profile} does not match the generated graph" >&2
             return 2
           }
         done < <(jq -c '.[]' <<<"''${profile_shard}")
       }

       validate_profile() {
         entry="$1"
         cache_available="$2"
         profile="$(jq -er '.profile' <<<"''${entry}")"
         build_input="$(jq -er '.build_input' <<<"''${entry}")"
         foundation="$(jq -er '.foundation' <<<"''${entry}")"
         hardware="$(jq -er '.hardware' <<<"''${entry}")"
         upstream_digest="$(jq -er '.upstream.digest' <<<"''${entry}")"
         upstream_name="$(jq -er '.upstream.image | if endswith("/bluefin-dx") then "bluefin-dx" else "bluefin" end' <<<"''${entry}")"
         upstream_image="$("''${FINITE_LOAD_BLUEFIN}" "''${upstream_name}")"
         target="$(jq -r '.target | tostring' <<<"''${entry}")"
         started_at="$(date +%s)"
    archive=""
    chunked_image=""
         primary_image="localhost/finite-validation:''${profile}-''${GITHUB_RUN_ID:-local}-''${GITHUB_RUN_ATTEMPT:-0}"
         parent_profile="$(jq -r '.parent // ""' <<<"''${entry}")"
         containerfile=./bootc/Containerfile
         base_ref="''${upstream_image}"
         parent_args=()
         if [[ -n "''${parent_profile}" ]]; then
           containerfile=./bootc/Containerfile.derived
           if [[ -n "''${validated_images["''${parent_profile}"]:-}" ]]; then
             base_ref="''${validated_images["''${parent_profile}"]}"
           else
             parent_digest="$(jq -r '.parent_digest // ""' <<<"''${entry}")"
             parent_tag="$(jq -r '.parent_tag // ""' <<<"''${entry}")"
             [[ "''${parent_digest}" =~ ^sha256:[0-9a-f]{64}$ && -n "''${parent_tag}" ]] || {
               echo "''${profile}: selected derived profile has no candidate or immutable published parent" >&2
               return 2
             }
             base_ref="''${IMAGE_REF}@''${parent_digest}"
             "''${FINITE_PODMAN}" pull --quiet "''${base_ref}" >/dev/null
           fi
           parent_args+=(--build-arg "PARENT_PROFILE=''${parent_profile}")
         fi

         cache_ref="''${IMAGE_REF:?IMAGE_REF is required}-build-cache"
         cache_args=(--layers)
         if [[ "''${cache_available}" == true ]]; then
           cache_args+=(--cache-from "''${cache_ref}" --cache-ttl 168h)
         fi
         created="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
         echo "''${profile}: starting image build (target=''${target})"

         "''${FINITE_BUILDAH}" bud \
           --file "''${containerfile}" \
           --pull=missing \
           --network host \
           --security-opt label=disable \
           --build-context "finite-generated=''${FINITE_GENERATED_ROOT}" \
           "''${cache_args[@]}" \
           --label "io.finite.build.input=''${build_input}" \
           --label "io.finite.build.profile=''${profile}" \
           --label "io.finite.foundation=''${foundation}" \
           --label "io.finite.hardware=''${hardware}" \
           --label "io.finite.upstream.digest=''${upstream_digest}" \
           --label "org.opencontainers.image.base.digest=''${upstream_digest}" \
           --label "org.opencontainers.image.created=''${created}" \
           --label "org.opencontainers.image.revision=''${GITHUB_SHA:-local}" \
           "''${parent_args[@]}" \
           --build-arg "BASE_REF=''${base_ref}" \
           --build-arg "BUILD_PROFILE=''${profile}" \
           --build-arg "FINITE_VERSION=''${FINITE_VERSION}" \
           --format docker \
           --tls-verify=true \
           --tag "''${primary_image}" \
           .
         built_at="$(date +%s)"
         retained_images+=("''${primary_image}")
         echo "''${profile}: image build passed in $((built_at - started_at))s"

         if [[ "''${target}" != true ]]; then
           validated_images["''${profile}"]="''${primary_image}"
           echo "''${profile}: ancestor-only build retained as a local parent; target rechunk skipped"
           if [[ -n "''${GITHUB_STEP_SUMMARY:-}" ]]; then
             {
               echo "### Profile ''${profile}"
               echo
               echo "- Build input: \`''${build_input}\`"
               echo "- Bluefin digest: \`''${upstream_digest}\`"
               echo "- Registry cache available: \`''${cache_available}\`"
               echo "- Ancestor image build: \`$((built_at - started_at))s\`"
               echo "- Target rechunk validation: \`skipped (dependency only)\`"
             } >>"''${GITHUB_STEP_SUMMARY}"
           fi
           return
         fi

         rechunk_started_at="$(date +%s)"
         echo "''${profile}: starting target rechunk validation"
         output_dir="$(mktemp -d -p "''${RUNNER_TEMP:-''${TMPDIR:-/tmp}}" finite-rechunk.XXXXXX)"
         archive="''${output_dir}/finite.oci"
         rechunk_report="$(
           FINITE_PODMAN="''${FINITE_PODMAN}" \
             "''${FINITE_RECHUNK_IMAGE}" \
               --source "''${primary_image}" \
               --output "oci-archive:''${archive}"
         )"
         rechunk_mode="$(jq -er .mode <<<"''${rechunk_report}")"

         chunked_image="$("''${FINITE_PODMAN}" pull --quiet "oci-archive:''${archive}")"
         chunked_tag="''${primary_image}-chunked"
         "''${FINITE_PODMAN}" tag "''${chunked_image}" "''${chunked_tag}"
         validated_images["''${profile}"]="''${chunked_tag}"
         retained_images+=("''${chunked_image}" "''${chunked_tag}")
         rm -f -- "''${archive}"
         rmdir -- "''${archive%/*}" 2>/dev/null || true
    archive=""

         finished_at="$(date +%s)"
         echo "''${profile}: target rechunk passed in $((finished_at - rechunk_started_at))s (''${rechunk_mode}); total validation $((finished_at - started_at))s"
         if [[ -n "''${GITHUB_STEP_SUMMARY:-}" ]]; then
           {
             echo "### Profile ''${profile}"
             echo
             echo "- Build input: \`''${build_input}\`"
             echo "- Bluefin digest: \`''${upstream_digest}\`"
             echo "- Registry cache available: \`''${cache_available}\`"
             echo "- Image build: \`$((built_at - started_at))s\`"
             echo "- Target rechunk validation: \`$((finished_at - rechunk_started_at))s\` (\`''${rechunk_mode}\`)"
             echo "- Total validation: \`$((finished_at - started_at))s\`"
           } >>"''${GITHUB_STEP_SUMMARY}"
         fi
       }

       validate_contract
       case "''${1:-}" in
         "") ;;
         --check)
           jq -c '[.[].profile]' <<<"''${profile_shard}"
           exit 0
           ;;
         *)
           usage
           exit 2
           ;;
       esac

       : "''${FINITE_BUILDAH:?FINITE_BUILDAH is required}"
       : "''${FINITE_PODMAN:?FINITE_PODMAN is required}"
       cache_ref="''${IMAGE_REF:?IMAGE_REF is required}-build-cache"
       cache_available=false
       if skopeo list-tags "docker://''${cache_ref}" >/dev/null 2>&1; then
         cache_available=true
       fi

       while IFS= read -r entry; do
         profile="$(jq -er '.profile' <<<"''${entry}")"
         echo "Validating ''${profile} from its locked Bluefin foundation"
         validate_profile "''${entry}" "''${cache_available}"
         echo "''${profile}: validation passed"
       done < <(jq -c '.[]' <<<"''${profile_shard}")
  '';
}
