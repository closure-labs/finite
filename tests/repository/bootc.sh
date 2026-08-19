#!/usr/bin/env bash
set -euo pipefail

bash tests/bootc/derived-profile.sh
bash tests/bootc/plan.sh
bash tests/bootc/reuse-image.sh
bash tests/bootc/sbom.sh
bash tests/bootc/shards.sh
