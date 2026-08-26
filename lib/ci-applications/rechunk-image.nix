{pkgs}:
pkgs.writeShellApplication {
  name = "finite-rechunk-image";
  runtimeInputs = with pkgs; [bash coreutils gnugrep jq podman skopeo];
  text = ''
    set -euo pipefail

    usage() {
      cat >&2 <<'EOF'
    usage: finite-rechunk-image --source IMAGE --output TRANSPORT \
             [--previous-build docker://IMAGE@sha256:DIGEST] [--authfile FILE]
    EOF
    }

    source_image=
    output=
    previous_build=
    authfile=
    while (($#)); do
      case "$1" in
        --source)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          source_image=$2
          shift 2
          ;;
        --output)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          output=$2
          shift 2
          ;;
        --previous-build)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          previous_build=$2
          shift 2
          ;;
        --authfile)
          [[ $# -ge 2 ]] || { usage; exit 2; }
          authfile=$2
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
    [[ -n "''${source_image}" && -n "''${output}" ]] || { usage; exit 2; }
    if [[ -n "''${authfile}" && ! -f "''${authfile}" ]]; then
      echo "Registry authentication file is missing: ''${authfile}" >&2
      exit 2
    fi

    podman="''${FINITE_PODMAN:-${pkgs.podman}/bin/podman}"
    skopeo="''${FINITE_SKOPEO:-${pkgs.skopeo}/bin/skopeo}"
    preserved_labels="$({
      "''${podman}" inspect "''${source_image}" |
        jq -c '
          .[0].Config.Labels // {} |
          with_entries(
            select(
              .key != "containers.bootc" and
              .key != "io.buildah.version" and
              (.key | startswith("ostree.") | not)
            )
          )
        '
    })"
    label_args=()
    while IFS= read -r label; do
      label_args+=(--label "''${label}")
    done < <(jq -r 'to_entries[] | "\(.key)=\(.value)"' <<<"''${preserved_labels}")

    # rpm-ostree's full and --previous-build paths require more than the
    # ordinary rootless Podman capability set. A 2026-08-26 fixture run proved
    # SYS_ADMIN alone fails while both privileged paths succeed. Keep the
    # privileged container constrained to the read-only image mount below,
    # one isolated output mount, and the optional read-only auth file. No host
    # devices or other host paths are exposed.
    run_args=(--rm --pull=never --privileged)
    if [[ -n "''${authfile}" ]]; then
      run_args+=(
        --env REGISTRY_AUTH_FILE=/run/registry-auth.json
        --volume "''${authfile}:/run/registry-auth.json:ro"
      )
    fi
    container_output="''${output}"
    if [[ "''${output}" == oci-archive:/* ]]; then
      archive_path="''${output#oci-archive:}"
      archive_dir="$(dirname -- "''${archive_path}")"
      [[ -d "''${archive_dir}" ]] || {
        echo "OCI archive output directory is missing: ''${archive_dir}" >&2
        exit 2
      }
      archive_name="$(basename -- "''${archive_path}")"
      container_output="oci-archive:/run/finite-rechunk-output/''${archive_name}"
      run_args+=(--volume "''${archive_dir}:/run/finite-rechunk-output")
    fi
    run_args+=(
      # Podman image mounts are read-only unless rw=true is specified.
      --mount "type=image,src=''${source_image},target=/rpm-ostree"
      --entrypoint /usr/bin/rpm-ostree
      "''${source_image}"
    )

    previous_digest=none
    incremental_available=false
    if [[ -n "''${previous_build}" ]]; then
      if [[ "''${previous_build}" =~ ^docker://.+@sha256:[0-9a-f]{64}$ ]]; then
        previous_digest="''${previous_build##*@}"
        help_output="$({
          "''${podman}" run --rm --pull=never \
            --entrypoint /usr/bin/rpm-ostree \
            "''${source_image}" \
            compose build-chunked-oci --help 2>&1 || true
        })"
        if grep -Eq '(^|[[:space:]])--previous-build([=[:space:]]|$)' <<<"''${help_output}"; then
          incremental_available=true
        else
          echo 'Source rpm-ostree does not support --previous-build; using a full rechunk' >&2
        fi
      else
        echo 'Previous build is not an immutable docker reference; using a full rechunk' >&2
      fi
    fi

    run_rechunk() {
      local incremental=$1
      local previous_args=()
      if [[ "''${incremental}" == true ]]; then
        previous_args+=(--previous-build "''${previous_build}")
      fi
      "''${podman}" run "''${run_args[@]}" \
        compose build-chunked-oci \
          --max-layers 127 \
          --format-version=2 \
          "''${label_args[@]}" \
          "''${previous_args[@]}" \
          --bootc \
          --rootfs /rpm-ostree \
          --output "''${container_output}" >&2
    }

    started="''${SECONDS}"
    mode=full
    if [[ "''${incremental_available}" == true ]]; then
      if run_rechunk true; then
        mode=incremental
      else
        echo 'Incremental rechunk failed; retrying with the full rechunk path' >&2
        run_rechunk false
      fi
    else
      run_rechunk false
    fi
    rechunk_seconds=$((SECONDS - started))

    skopeo_args=(--retry-times 3)
    if [[ -n "''${authfile}" ]]; then
      skopeo_args+=(--authfile "''${authfile}")
    fi
    metadata="$("''${skopeo}" inspect "''${skopeo_args[@]}" "''${output}")"
    jq -e --argjson expected "''${preserved_labels}" '
      (.Labels // {}) as $actual |
      $expected | to_entries | all(.[]; $actual[.key] == .value)
    ' <<<"''${metadata}" >/dev/null
    digest="$(jq -er '.Digest' <<<"''${metadata}")"
    [[ "''${digest}" =~ ^sha256:[0-9a-f]{64}$ ]]

    jq -cn \
      --arg digest "''${digest}" \
      --arg mode "''${mode}" \
      --arg previous_build_digest "''${previous_digest}" \
      --argjson rechunk_seconds "''${rechunk_seconds}" \
      '{
        digest: $digest,
        mode: $mode,
        previous_build_digest: $previous_build_digest,
        rechunk_seconds: $rechunk_seconds
      }'
  '';
}
