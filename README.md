<h1 align="center"><img src="modules/aspects/base/rootfs/usr/share/finite/finite-logo.png" alt="Finite logo" width="72" align="absmiddle"> Finite</h1>

<p align="center"><strong>Your workstation, finished.</strong></p>

<p align="center">
  A signed, atomic Linux desktop built on Bluefin.<br>
  Reliable enough to forget about. Personal enough to make your own.
</p>

<p align="center">
  <a href="docs/installation.md">Install Finite</a> ·
  <a href="docs/configuration.md">Make it yours</a> ·
  <a href="docs/README.md">Technical documentation</a>
</p>

---

## Calm by default

Finite keeps the operating system and your workspace separate. The system is a
signed, transactional image; your tools and preferences are a declarative Home
Manager profile. Updates are predictable, rollbacks are built in, and changing
how you work never means rebuilding the whole machine.

**Safe underneath.** Atomic bootc updates replace the system as a unit instead
of modifying it package by package.

**Yours on top.** Choose any mix of Developer, Sales, Trainer, Support,
Executive, and IT roles—or start with a clean base.

**Ready for real hardware.** Use the generic image on most x86-64 computers, or
the vendor-neutral next image when you need the upstream Fedora 7.2 kernel.

## Start simply

### Bring an existing bootc system

Switch to the standard Finite image and reboot:

```console
sudo bootc switch ghcr.io/closure-labs/finite:latest
sudo systemctl reboot
```

On first login, Finite asks how you use your computer. Select the roles you
want, choose **Configure**, and it builds your personal environment. You can
change that selection at any time with `finite-configure`.

### Set up a new machine

The Finite installer provides a familiar graphical setup while installing the
exact signed image recorded in its manifest. Follow the
[installation guide](docs/installation.md) to choose an image, verify the ISO,
and install it.

## Choose your foundation

For most people, `latest` is the right place to begin. It tracks the standard
Bluefin foundation on generic x86-64 hardware.

| If you want… | Start with… |
| --- | --- |
| A focused everyday workstation | `latest` or `bluefin-generic` |
| Developer tools in the system foundation | `bluefin-dx-generic` |
| Fedora 7.2 hardware support, including Intel IPU7 | `bluefin-next` or `bluefin-dx-next` |

Bluefin and Bluefin DX can both use every Finite role. The image chooses the
system foundation and kernel channel; your roles and optional Home Manager
hardware tuning choose the workspace.

## Keep moving

Update the operating system when it suits you:

```console
sudo bootc upgrade
sudo systemctl reboot
```

Update your personal environment independently:

```console
nh home switch --update-input finite
```

If a system deployment does not work for you, `sudo bootc rollback` selects the
previous image for the next boot. The [installation and update
reference](docs/installation.md) covers image selection, provisioning, ISO
verification, and recovery in detail.

## Built in the open

Finite is composed with Nix, built as bootc images, signed with keyless Sigstore
identity, and published with provenance and software-bill-of-materials
attestations. The repository is both the product definition and the record of
how each image was assembled.

Want to work on Finite itself? The [development guide](docs/development.md)
covers the development shell, focused checks, generated outputs, local image
builds, and repository layout.

---

## Documentation

This README is the quick tour. Installation, configuration, architecture,
operations, security boundaries, and troubleshooting live in the
**[Finite technical documentation](docs/README.md)**.
