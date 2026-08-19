#!/usr/bin/env bash
set -euo pipefail

bash tests/automation/classify-changes.sh
bash tests/automation/classify-ci.sh
bash tests/automation/ci-gate.sh
bash tests/automation/promote-images.sh
bash tests/automation/trusted-update.sh
