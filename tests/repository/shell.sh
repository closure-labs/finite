#!/usr/bin/env bash
set -euo pipefail

mapfile -d $'\0' shell_files < <(
  find automation bootc modules tests -type f -name '*.sh' -print0
)
bash -n "${shell_files[@]}"
# Dynamic container build roots cannot be followed statically. Every sourced
# shell file is already present in this complete input array.
shellcheck --exclude=SC1091 --external-sources --source-path=SCRIPTDIR \
  "${shell_files[@]}"
