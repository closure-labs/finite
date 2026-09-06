#!/usr/bin/env bash
set -euo pipefail
profile="${1:?profile required}"
channel="${2:?channel required}"
published="${3:-false}"
repository=ghcr.io/closure-labs/finite
mkdir -p .bluebuild
if [[ $published == true ]]; then
  docker pull "$repository:$channel"
  image=$(docker inspect --format '{{index .RepoDigests 0}}' "$repository:$channel")
  cosign verify --key cosign.pub "$image" >".bluebuild/$profile-signature.json"
else
  mapfile -t images < <(docker image ls --filter "label=io.finite.profile=$profile" --format '{{.ID}}' | sort -u)
  [[ ${#images[@]} == 1 ]] || {
    echo "Expected one assembled $profile image, found ${#images[@]}" >&2
    docker image ls
    exit 1
  }
  image=${images[0]}
fi
docker inspect "$image" >".bluebuild/$profile-image.json"
jq -e --arg revision "${GITHUB_SHA:-local}" '
  .[0].Config.Labels |
  .["org.opencontainers.image.revision"] == $revision and
  .["org.opencontainers.image.source"] == "https://github.com/closure-labs/finite"
' ".bluebuild/$profile-image.json" >/dev/null
expected_kernel=$(jq -r .release sources/kernel-next.json)
docker run --rm --privileged --entrypoint /bin/bash \
  -v "$PWD/scripts/bluebuild/verify-image.sh:/run/verify-image.sh:ro" \
  "$image" /run/verify-image.sh "$profile" "$repository" "$expected_kernel"
jq -e '.[0].Config.Labels["org.opencontainers.image.base.digest"] |
  test("^sha256:[0-9a-f]{64}$")' ".bluebuild/$profile-image.json"
printf '%s\n' "$image" >".bluebuild/$profile-image-ref.txt"
