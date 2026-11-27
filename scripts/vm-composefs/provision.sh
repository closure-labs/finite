#!/usr/bin/bash
# Ephemeral VM account only; no private SSH key is included in the image.
set -euo pipefail
mkdir -p /var/roothome/.ssh
install -m600 /usr/share/finite-vm/ssh-key.pub /var/roothome/.ssh/authorized_keys
restorecon -RF /var/roothome/.ssh
passwd -d root
mkdir -p /etc/ssh/sshd_config.d
printf 'PermitRootLogin prohibit-password\nPasswordAuthentication no\n' >/etc/ssh/sshd_config.d/10-finite-vm.conf
restorecon -RF /etc/ssh/sshd_config.d
