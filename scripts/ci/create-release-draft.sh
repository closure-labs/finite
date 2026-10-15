#!/usr/bin/env bash
# The caller validates evidence and resolves only release-publishing credentials.
set -euo pipefail
unset MERGE_QUEUE_TOKEN COSIGN_PRIVATE_KEY COSIGN_PASSWORD
[[ ${GITHUB_ACTIONS:-} == true && ${GITHUB_REPOSITORY:-} == closure-labs/finite && ${GITHUB_REF:-} == refs/heads/main && ${GITHUB_EVENT_NAME:-} == workflow_dispatch ]]
[[ ${RELEASE_SOURCE_SHA:-} =~ ^[0-9a-f]{40}$ ]]
version=$(<VERSION)
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]
case "${RELEASE_TAG:-}" in
  finite-finite-"$version"|finite-finite-dev-"$version") ;;
  *) exit 2 ;;
esac
test -s .bluebuild/release/SHA256SUMS
test -s .bluebuild/release/SHA256SUMS.bundle.json
test -s .bluebuild/release/provenance.json
python3 -c 'import json,os; p=json.load(open(".bluebuild/release/provenance.json")); assert p["revision"] == os.environ["RELEASE_SOURCE_SHA"]'
# A draft can exist before its tag. GET releases/tags exposes published releases
# only. This push-capable token's full bounded list is authoritative for drafts:
# https://docs.github.com/en/rest/releases/releases#list-releases
python3 - <<'PY'
import json, os, resource, subprocess, tempfile
remaining = 4 * 1024**2
for page in range(1, 11):
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(['gh', 'api', 'repos/' + os.environ['GITHUB_REPOSITORY'] + '/releases?per_page=100&page=' + str(page)],
            stdout=output, stderr=subprocess.DEVNULL, check=False, timeout=90,
            preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024**2, 4 * 1024**2)))
        size = output.tell(); remaining -= size
        if result.returncode or not 0 < size <= 4 * 1024**2 or remaining < 0:
            raise SystemExit('Bounded authenticated release listing failed')
        output.seek(0); releases = json.load(output)
    if not isinstance(releases, list) or len(releases) > 100 or any(not isinstance(item, dict) or not isinstance(item.get('tag_name'), str) for item in releases):
        raise SystemExit('Invalid release listing')
    if any(item['tag_name'] == os.environ['RELEASE_TAG'] for item in releases):
        raise SystemExit('An existing draft or published release already claims this tag')
    if len(releases) < 100: break
else:
    raise SystemExit('Release pagination budget exhausted before proving absence')
PY
# Workflows:write is needed when the historical target differs in workflows
# from default. GITHUB_TOKEN cannot receive that permission:
# https://docs.github.com/en/rest/releases/releases#create-a-release
# POST is deliberately create-only: never update/delete a claimed tag or draft.
gh api --method POST "repos/$GITHUB_REPOSITORY/git/refs" \
  -f "ref=refs/tags/$RELEASE_TAG" -f "sha=$RELEASE_SOURCE_SHA" >/dev/null
gh api "repos/$GITHUB_REPOSITORY/git/ref/tags/$RELEASE_TAG" |
  python3 -c 'import json,os,sys; r=json.load(sys.stdin); assert r["ref"] == "refs/tags/"+os.environ["RELEASE_TAG"] and r["object"]["type"] == "commit" and r["object"]["sha"] == os.environ["RELEASE_SOURCE_SHA"]'
gh release create "$RELEASE_TAG" .bluebuild/release/* --draft --verify-tag \
  --title "$RELEASE_TAG" --notes 'Qualified image, signed checksums, enforced vulnerability policy, SBOM, provenance and acceptance evidence. Review before publishing. Large ISO images are split; concatenate parts in filename order before use.'
