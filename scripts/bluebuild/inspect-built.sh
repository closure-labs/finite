#!/usr/bin/env bash
set -euo pipefail
profile="${1:?profile required}"
channel="${2:?channel required}"
published="${3:-false}"
repository=ghcr.io/closure-labs/finite
mkdir -p .bluebuild
record=".bluebuild/$profile-publication.json"
jq -e --arg channel "$channel" --arg profile "$profile" \
  '.profile == $profile and (.tags | index($channel) != null)' "$record" >/dev/null
expected_base=$(jq -er .digest "$record")
if [[ $published == true ]]; then
  candidate=$(jq -er .candidate "$record")
  # Resolve once, then pull and inspect that immutable candidate throughout.
  candidate_digest=$(timeout 150s skopeo --command-timeout 30s inspect --retry-times 3 --no-tags \
    "docker://$repository:$candidate" | jq -er .Digest)
  [[ $candidate_digest =~ ^sha256:[0-9a-f]{64}$ ]]
  image="$repository@$candidate_digest"
  # Large Bluefin images can take more than five minutes on a cold runner.
  for attempt in 1 2 3; do
    echo "Pulling $image (attempt $attempt/3, timeout 15m)"
    if timeout 15m docker pull "$image"; then
      break
    else
      status=$?
    fi
    if [[ $status == 124 ]]; then
      echo "Image pull timed out after 15m (attempt $attempt/3)" >&2
    else
      echo "Image pull failed with exit code $status (attempt $attempt/3)" >&2
    fi
    if [[ $attempt == 3 ]]; then
      echo "Unable to pull $image after 3 attempts; verification cannot continue" >&2
      exit "$status"
    fi
    echo "Retrying image pull in 10 seconds" >&2
    sleep 10
  done
  timeout 150s cosign verify --key cosign.pub "$image" >".bluebuild/$profile-signature.json"
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
jq -e --arg revision "${GITHUB_SHA:-local}" --arg base "$expected_base" --arg profile "$profile" '
  .[0].Config.Labels |
  .["org.opencontainers.image.revision"] == $revision and
  .["org.opencontainers.image.base.digest"] == $base and
  .["io.finite.profile"] == $profile and
  .["org.opencontainers.image.source"] == "https://github.com/closure-labs/finite"
' ".bluebuild/$profile-image.json" >/dev/null
expected_kernel=$(jq -r .release sources/kernel-next.json)
docker run --rm --privileged --entrypoint /bin/bash \
  -v "$PWD/scripts/bluebuild/verify-image.sh:/run/verify-image.sh:ro" \
  "$image" /run/verify-image.sh "$profile" "$repository" "$expected_kernel"
printf '%s\n' "$image" >".bluebuild/$profile-image-ref.txt"
