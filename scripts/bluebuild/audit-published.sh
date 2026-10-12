#!/usr/bin/env bash
set -euo pipefail
case "${CHANNEL:?}" in
  finite|finite-next|finite-dev|finite-dev-next) ;;
  *) echo 'Unsupported public channel' >&2; exit 2 ;;
esac
digest=$(skopeo --command-timeout 90s inspect --no-tags --format '{{.Digest}}' "docker://ghcr.io/closure-labs/finite:$CHANNEL")
[[ $digest =~ ^sha256:[0-9a-f]{64}$ ]]
image="ghcr.io/closure-labs/finite@$digest"
cosign verify --new-bundle-format=false --key cosign.pub "$image"
bash scripts/bluebuild/security-run.sh "$image" ".bluebuild/security-$CHANNEL"
