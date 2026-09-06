#!/usr/bin/env bash
set -euo pipefail
authselect select local with-silent-lastlog with-mdns4 with-fingerprint with-pam-u2f --force
authselect check
rm -rf /var/lib/authselect/backups
