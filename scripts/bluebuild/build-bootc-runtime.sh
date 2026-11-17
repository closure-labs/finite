#!/usr/bin/env bash
# Runs only in the isolated Fedora build container.
set -euo pipefail
test -f /source-lock.json
test -f /src/contrib/packaging/bootc.spec
readarray -t metadata < <(python3 - <<'PY'
import json
x=json.load(open('/source-lock.json'))
print(x['version'])
print(x['rpmRelease'])
PY
)
version=${metadata[0]}
release=${metadata[1]}
[[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $release =~ ^[0-9A-Za-z.]+$ ]]
export SOURCE_DATE_EPOCH=0
mkdir -p /tmp/rpmbuild/{SPECS,RPMS,BUILDROOT}
# Keep upstream's packaging and complete runtime/initramfs payload. A low RPM
# release lets Fedora's official package replace this temporary build naturally.
sed -e "s/^Version:.*/Version: $version/" -e "s/^Release:.*/Release: $release%{?dist}/" \
  -e '/^%autochangelog$/d' \
  -e 's/cargo build -j%{_smp_build_ncpus} --release/cargo build --locked --offline -j%{_smp_build_ncpus} --release/' \
  /src/contrib/packaging/bootc.spec >/tmp/rpmbuild/SPECS/bootc.spec
rpmbuild -bb --nocheck --without check --without tests \
  --define '_topdir /tmp/rpmbuild' --define '_builddir /src' --define 'container_build 1' \
  --define '_smp_build_ncpus 1' --define 'debug_package %{nil}' \
  --define '_buildhost finite-bootc-runtime' \
  --define 'use_source_date_epoch_as_buildtime 1' --define 'clamp_mtime_to_source_date_epoch 1' \
  /tmp/rpmbuild/SPECS/bootc.spec
mkdir /out
mapfile -t packages < <(find /tmp/rpmbuild/RPMS -name "bootc-$version-$release*.x86_64.rpm")
[[ ${#packages[@]} == 1 ]]
cp "${packages[0]}" /out/bootc-runtime.rpm
cp /source-lock.json /out/source-lock.json
rpm -qp --qf '%{NAME} %{VERSION}-%{RELEASE}.%{ARCH}\n' /out/bootc-runtime.rpm
