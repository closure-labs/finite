#!/usr/bin/env bash
# Install the same source-locked runtime used by the native installer.
set -euo pipefail
work=/usr/lib/finite/bootc-build
python3 - "$work" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
p=Path(sys.argv[1])
r=json.loads((p/'receipt.json').read_text())
for name,field in [('source-lock.json','sourceLockSha256'),('bootc-runtime.rpm','rpmSha256')]:
 with (p/name).open('rb') as stream:
  if hashlib.file_digest(stream,'sha256').hexdigest()!=r[field]:
   raise SystemExit('Native bootc build receipt differs from its payload')
pin=json.loads((p/'source-lock.json').read_text())
fedora=pin['buildFedoraVersion']
if subprocess.check_output(['rpm','--eval','%{?fedora}'],text=True).strip()!=str(fedora):
 raise SystemExit(f'Native bootc RPM requires a Fedora {fedora} image base')
PY
# Base images already carry bootc's runtime dependencies. RPM checks those
# dependencies locally; do not consult moving mirrors or install a different
# release while applying this checked source package.
rpm -Uvh --oldpackage --replacepkgs "$work/bootc-runtime.rpm"
python3 - "$work" <<'PY'
import hashlib,json,subprocess,sys
from pathlib import Path
p=Path(sys.argv[1]); pin=json.loads((p/'source-lock.json').read_text())
expected=f"{pin['version']}-{pin['rpmRelease']}.fc{pin['buildFedoraVersion']}"
actual=subprocess.check_output(['rpm','-q','--qf','%{VERSION}-%{RELEASE}','bootc'],text=True)
if actual!=expected or subprocess.check_output(['bootc','--version'],text=True).strip()!='bootc '+pin['version']:
 raise SystemExit('Installed bootc differs from the locked native runtime')
files={}
for name in ['/usr/bin/bootc','/usr/lib/bootc/initramfs-setup']:
 with open(name,'rb') as stream: files[name]=hashlib.file_digest(stream,'sha256').hexdigest()
out=Path('/usr/share/finite/bootc-runtime.json');out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps({'schema':1,'source':pin,'rpm':actual,'files':files},indent=2)+'\n')
PY
rm -rf -- "$work"
