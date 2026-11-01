#!/usr/bin/env bash
# Functional checks run in a separate process so recording failure cannot disable
# errexit in a remote command or skip the remaining OS lifecycle assertions.
set -euo pipefail
operation=${1:?}; state=${2:?}; profile=${3:?}; phase_name=${4:?}; key=${5:?}
shift 5
ssh_args=("$@")
secrets=$(dirname "$key")
case "$operation" in
initialize)
ssh "${ssh_args[@]}" bash -s -- "$profile" "$phase_name" <<'GUEST' 2>&1 | python3 scripts/bluebuild/guest-timings.py "$state/guest-timings.json" --log "$state/home-init.log.gz" --secret "$secrets/luks-key"
set -euo pipefail
guest_now() {
  local uptime unused
  read -r uptime unused </proc/uptime
  printf '%s\n' "${uptime%.*}"
}
guest_stage=
guest_started=0
guest_finish() {
  local status=$1
  if [[ -n $guest_stage ]]; then
    printf 'FINITE_GUEST_STAGE %s %s %s\n' "$guest_stage" "$(($(guest_now) - guest_started))" "$status"
    guest_stage=
  fi
}
guest_begin() {
  guest_finish 0
  guest_stage=$1
  guest_started=$(guest_now)
}
trap 'guest_finish "$?"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
guest_begin startup-checks
jq -n --arg foundation "$(jq -r .foundation /usr/share/finite/profile.json)" \
  '{schema:3,foundation:$foundation,hardware:"generic-x86_64",packages:[],roles:[],capabilities:[],identity:{}}' >"$HOME/profile.json"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$XDG_RUNTIME_DIR/bus"
export FINITE_NIX_COMMAND=/nix/var/nix/profiles/default/bin/nix
# Budget from the guest's CPUs/RAM, not the host runner. Preserve inherited config.
export NIX_CONFIG="${NIX_CONFIG:-}
$(python3 /var/lib/finite-vm/nix-resources.py --config)"
python3 /var/lib/finite-vm/nix-resources.py --verify --nix "$FINITE_NIX_COMMAND"
guest_begin homebrew-setup
echo 'Checking the desktop user and shared Homebrew initialization'
[[ $(id -u) == 1000 && $(id -g) == 1000 ]]
sudo systemctl start brew-setup.service
stat -c '%u:%g %a %n' /home/linuxbrew/.linuxbrew /home/linuxbrew/.linuxbrew/Homebrew
[[ -w /home/linuxbrew/.linuxbrew/Homebrew && -w /home/linuxbrew/.linuxbrew/Cellar ]]
guest_begin predecessor-preparation
if [[ $2 == upgrade ]]; then
  bash /var/lib/finite-vm/prepare-predecessor-home
fi
guest_begin home-init
echo 'Building and activating the base Home Manager environment'
FOUNDATION_TIMINGS=1 /usr/libexec/finite/home-init --profile "$HOME/profile.json" </dev/null 2>&1
GUEST
# A diagnostic storage failure is distinct from the guest process exit. The
# pipeline above preserves a nonzero SSH status; only successful guests reach
# this fail-closed evidence check, after all guest output has been drained.
python3 - "$state/home-init-log.json" <<'CAPTURE'
import json
import sys
with open(sys.argv[1]) as stream:
    receipt = json.load(stream)
if receipt.get('captureComplete') is not True:
    raise SystemExit('VM diagnostic evidence incomplete; guest exit status is recorded separately')
CAPTURE
# Initializers and their children must not consume commands from bash -s stdin.
# Establish the fixture over a separate SSH request, then prove it exists before
# changing deployments so an uncreated marker cannot masquerade as data loss.
ssh "${ssh_args[@]}" python3 - >"$state/initialized-home.json" <<'HOME_INITIALIZED'
import hashlib
import json
from pathlib import Path

configuration = Path.home() / '.config/home-manager'
customization = configuration / 'customize.nix'
for name in ('flake.nix', 'flake.lock', 'profile.json', 'customize.nix'):
    if not (configuration / name).is_file():
        raise ValueError('Home initialization did not produce the required configuration file: ' + name)
if Path('/var/home/nix/finite-acceptance').read_text().rstrip('\n') != 'persistent-nix-state':
    raise ValueError('Nix persistence fixture was not initialized')
with customization.open('a') as output:
    output.write('\n# VM acceptance customization\n')
content = customization.read_bytes()
if b'VM acceptance customization' not in content:
    raise ValueError('Home customization fixture was not initialized')
print(json.dumps({'schema': 1, 'status': 'pass', 'checks': {'nixState': True, 'homeCustomization': True},
                  'customizationSha256': hashlib.sha256(content).hexdigest()}))
HOME_INITIALIZED

;;
updated)
ssh "${ssh_args[@]}" python3 - >"$state/updated-home.json" <<'HOME_PERSISTENCE'
import json
from pathlib import Path
import sys

checks = {}
errors = []
for name, path, expected, exact in (
    ('nixState', Path('/var/home/nix/finite-acceptance'), 'persistent-nix-state', True),
    ('homeCustomization', Path.home() / '.config/home-manager/customize.nix', 'VM acceptance customization', False),
):
    try:
        content = path.read_text()
        matched = content.rstrip('\n') == expected if exact else expected in content
        checks[name] = matched
        if not matched:
            errors.append(f'{name}: persisted marker changed at {path}')
    except OSError as error:
        checks[name] = False
        errors.append(f'{name}: cannot read {path}: {error.strerror}')
print(json.dumps({'schema': 1, 'status': 'pass' if all(checks.values()) else 'fail', 'checks': checks, 'errors': errors}))
for error in errors:
    print('Post-upgrade persistence check failed: ' + error, file=sys.stderr)
raise SystemExit(bool(errors))
HOME_PERSISTENCE
;;
*) echo "Unknown VM functional operation" >&2; exit 2 ;;
esac
