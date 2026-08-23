#!/usr/bin/env bash
set -euo pipefail

test_root="$(mktemp -d)"
trap 'rm -rf -- "${test_root}"' EXIT
fake_cosign="${test_root}/cosign"

printf '#!%s\n' "${BASH}" >"${fake_cosign}"
cat >>"${fake_cosign}" <<'EOF'
set -euo pipefail

case "${1:-}" in
	sign)
		count=0
		[[ ! -f "${FAKE_SIGN_COUNT}" ]] || read -r count <"${FAKE_SIGN_COUNT}"
		count=$((count + 1))
		printf '%s\n' "${count}" >"${FAKE_SIGN_COUNT}"
		((count > FAKE_SIGN_FAILURES))
		;;
	verify)
		count=0
		[[ ! -f "${FAKE_VERIFY_COUNT}" ]] || read -r count <"${FAKE_VERIFY_COUNT}"
		count=$((count + 1))
		printf '%s\n' "${count}" >"${FAKE_VERIFY_COUNT}"
		printf '%s\n' "$*" >"${FAKE_VERIFY_LOG}"
		((count > FAKE_VERIFY_FAILURES))
		;;
	*)
		exit 2
		;;
esac
EOF
chmod 0755 "${fake_cosign}"

export COSIGN_IDENTITY=https://github.com/example/finite/.github/workflows/build-profile.yml@refs/heads/main
export DIGEST=sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee
export IMAGE_REF=ghcr.io/example/finite
export FINITE_COSIGN="${fake_cosign}"
export FINITE_COSIGN_RETRY_DELAY_SECONDS=0
export FINITE_COSIGN_SIGN_ATTEMPTS=2
export FINITE_COSIGN_VERIFY_ATTEMPTS=4
export FAKE_SIGN_COUNT="${test_root}/sign-count"
export FAKE_VERIFY_COUNT="${test_root}/verify-count"
export FAKE_VERIFY_LOG="${test_root}/verify-log"

export FAKE_SIGN_FAILURES=1
export FAKE_VERIFY_FAILURES=2
finite-image-sign
test "$(<"${FAKE_SIGN_COUNT}")" = 2
test "$(<"${FAKE_VERIFY_COUNT}")" = 3
grep -qF -- "--certificate-identity ${COSIGN_IDENTITY}" "${FAKE_VERIFY_LOG}"
grep -qF "${IMAGE_REF}@${DIGEST}" "${FAKE_VERIFY_LOG}"

printf '0\n' >"${FAKE_SIGN_COUNT}"
printf '0\n' >"${FAKE_VERIFY_COUNT}"
export FAKE_SIGN_FAILURES=0
export FAKE_VERIFY_FAILURES=99
if finite-image-sign; then
	echo 'Expected permanent signature verification failure' >&2
	exit 1
fi
test "$(<"${FAKE_SIGN_COUNT}")" = 1
test "$(<"${FAKE_VERIFY_COUNT}")" = 5

printf '0\n' >"${FAKE_SIGN_COUNT}"
printf '0\n' >"${FAKE_VERIFY_COUNT}"
export FAKE_VERIFY_FAILURES=0
finite-image-sign
test "$(<"${FAKE_SIGN_COUNT}")" = 0
test "$(<"${FAKE_VERIFY_COUNT}")" = 1
