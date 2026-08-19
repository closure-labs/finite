#!/usr/bin/env bash
set -euo pipefail

bash modules/aspects/base/tests/contracts.sh
bash modules/aspects/base/tests/nix-lifecycle.sh
bash modules/aspects/capabilities/devops/tests/contracts.sh
bash modules/aspects/roles/support/tests/contracts.sh
bash modules/aspects/hardware/dell-xps-9350-intel/tests/lid-auth.sh
bash modules/aspects/hardware/dell-xps-9350-intel/tests/policies.sh
