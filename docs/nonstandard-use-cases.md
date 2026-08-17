# Nonstandard use cases

## Track another profile

Switch to a complete published profile and reboot:

```bash
run0 bootc switch ghcr.io/declarative-dale/purplefin:support-generic
run0 systemctl reboot
```

The selected tag carries both the workload and hardware configuration.

## Register a security key

Every hardware profile includes PAM U2F/FIDO2 and YubiKey tooling. Register a
key for the current user:

```bash
mkdir -p ~/.config/Yubico
pamu2fcfg >~/.config/Yubico/u2f_keys
```

The mapping remains in the user's home directory.

## Keep a laptop awake with its lid closed

While connected to AC power, start Purplefin's session-scoped inhibitor:

```bash
purplefin-caffeinate on
purplefin-caffeinate status
```

Restore normal lid and suspend behavior with:

```bash
purplefin-caffeinate off
```

The service uses `systemd-inhibit`, stops with the user session, and starts
only while the machine is connected to AC power.

## Complete the Bitwarden desktop migration

Current images install Bitwarden Desktop as a verified system Flatpak and ship
the native `bw` CLI as a Purplefin-built RPM. On the first boot, the ordered
first-boot service removes the legacy layered desktop RPM and stages a new
deployment when needed.

Sync the vault, upgrade, and reboot:

```bash
run0 bootc upgrade
run0 systemctl reboot
```

Check the first-boot task and reboot again when it staged a deployment:

```bash
systemctl status purplefin-firstboot-rpm-ostree.service
run0 systemctl reboot
```

Launch the Flatpak, sign in, and verify the installed desktop and CLI:

```bash
flatpak info --system com.bitwarden.desktop
rpm -q purplefin-bitwarden-cli
bw --version
test -f /usr/share/polkit-1/actions/com.bitwarden.Bitwarden.policy
```

Bitwarden's Flatpak stores its user state in
`~/.var/app/com.bitwarden.desktop/`. The native CLI keeps its existing
configuration.

## Complete the Nextcloud desktop migration

Current images install Nextcloud Desktop Client as a system Flatpak. After the
upgrade reboot, launch it and configure the account, then verify the package:

```bash
flatpak info --system com.nextcloud.desktopclient.nextcloud
```

The Flatpak stores its application state in
`~/.var/app/com.nextcloud.desktopclient.nextcloud/`.
