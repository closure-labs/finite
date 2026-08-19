#!/usr/bin/env bash
set -euo pipefail

latest_changelog_version="$({
  sed -nE 's/^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - [0-9]{4}-[0-9]{2}-[0-9]{2}$/\1/p' \
    CHANGELOG.md | head -n 1
})"
test -n "${latest_changelog_version}"
release_notes="$(purplefin-release-notes "${latest_changelog_version}" CHANGELOG.md)"
for heading in Added Changed Fixed Security; do
  grep -qF "### ${heading}" <<<"${release_notes}"
done
if grep -qF '[Unreleased]:' <<<"${release_notes}"; then
  echo 'release notes unexpectedly contain the Unreleased link target' >&2
  exit 1
fi
if [[ "$(<VERSION)" != *-dev.* ]]; then
  [[ "$(<VERSION)" == "${latest_changelog_version}" ]]
fi
