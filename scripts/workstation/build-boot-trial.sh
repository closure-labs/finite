#!/usr/bin/bash
# Runs only inside the build-tools container, with no network or host devices.
set -euo pipefail
umask 077
openssl req -new -x509 -newkey rsa:3072 -noenc -days 3650 \
  -subj '/CN=Finite workstation boot trial/' \
  -keyout /output/MOK.key -out /output/MOK.pem
openssl x509 -in /output/MOK.pem -outform DER -out /output/MOK.der
/usr/lib/systemd/ukify --config=/dev/null build \
  --linux=/inputs/linux --initrd=/inputs/initrd \
  --cmdline=@/inputs/cmdline --os-release=@/inputs/os-release \
  --uname="$(cat /inputs/uname)" \
  --secureboot-private-key=/output/MOK.key \
  --secureboot-certificate=/output/MOK.pem \
  --output=/output/finite-trial.efi
sbsign --key /output/MOK.key --cert /output/MOK.pem \
  --output /output/grubx64.efi \
  /usr/lib/systemd/boot/efi/systemd-bootx64.efi
for file in /output/finite-trial.efi /output/grubx64.efi; do
  sbverify --cert /output/MOK.pem "$file"
  objdump -h "$file" | grep -F .sbat
done
/usr/lib/systemd/ukify inspect /output/finite-trial.efi > /output/uki-inspect.txt
rpm -q systemd-boot-unsigned systemd-ukify sbsigntools > /output/tool-versions.txt
openssl x509 -in /output/MOK.pem -noout -fingerprint -sha256 > /output/certificate.txt
