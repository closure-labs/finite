#!/usr/bin/env bash
if [[ "${CI:-}" == true && $EUID -ne 0 && -z "${_PURPLEFIN_IN_USERNS:-}" ]]; then
  host_podman="$(PATH=/usr/local/bin:/usr/bin:/bin command -v podman || true)"
  [[ -n "${host_podman}" && "${host_podman}" != /nix/store/* ]] || {
    echo "The CI runner's host Podman is required to enter rootless storage" >&2
    exit 1
  }
  exec env _PURPLEFIN_IN_USERNS=1 "${host_podman}" unshare "$0" "$@"
fi
"${PURPLEFIN_VERIFY_BLUEFIN:?}" >/dev/null
source="docker://${PURPLEFIN_BLUEFIN_IMAGE:?}@${PURPLEFIN_BLUEFIN_DIGEST:?}"
image="${PURPLEFIN_BLUEFIN_IMAGE}:${PURPLEFIN_BLUEFIN_TAG:?}"
data_home="${XDG_DATA_HOME:-${HOME}/.local/share}"
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
graph_root="${CONTAINERS_STORAGE_GRAPHROOT:-${data_home}/containers/storage}"
run_root="${CONTAINERS_STORAGE_RUNROOT:-${runtime_dir}/containers}"
storage_driver="${CONTAINERS_STORAGE_DRIVER:-overlay}"
storage_ref="containers-storage:[${storage_driver}@${graph_root}+${run_root}]${image}"
install -d "${graph_root}" "${run_root}"
loaded_digest="$(
  skopeo inspect --format '{{.Digest}}' "${storage_ref}" 2>/dev/null || true
)"
if [[ "${loaded_digest}" != "${PURPLEFIN_BLUEFIN_DIGEST}" ]]; then
  skopeo copy \
    --override-arch "${PURPLEFIN_BLUEFIN_ARCHITECTURE:?}" \
    --override-os linux \
    --preserve-digests \
    --retry-times 3 \
    "${source}" \
    "${storage_ref}" >&2
  loaded_digest="$(
    skopeo inspect --format '{{.Digest}}' "${storage_ref}"
  )"
fi
[[ "${loaded_digest}" == "${PURPLEFIN_BLUEFIN_DIGEST}" ]] || {
  echo "Loaded Bluefin digest ${loaded_digest} does not match ${PURPLEFIN_BLUEFIN_DIGEST}" >&2
  exit 1
}
printf '%s\n' "${image}"
