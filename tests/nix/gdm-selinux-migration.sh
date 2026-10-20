#!/usr/bin/env bash
set -euo pipefail
repository=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
exec /usr/bin/bash "$repository/scripts/bluebuild/check-vm-gdm-labels.sh" "$@"
