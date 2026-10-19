# Roadmap

Finite focuses on a personal workstation with recoverable updates, useful app
choices and clear security decisions. The two active profiles are `finite`
and `finite-dev`, built on approved Bluefin and Bluefin DX images.

## Delivery priorities

| Priority | Result | Evidence |
| --- | --- | --- |
| Human security decisions | Super Admins review new or worsened risk once; covered builds proceed unattended | [Implementation and rollout](ci-maintainer-decisions.md) |
| Recoverable system updates | Each published digest passes signed fresh-install, upgrade and rollback qualification | [Workstation qualification](workstation-qualification.md) |
| Consistent official releases | One review binds both profiles' versions, images, qualified ISOs and assets | [Release coordinator](release-set-controller.md) |
| Personal app maintenance | Users choose roles, preserve custom modules and control Foundation updates | [Configuration](configuration.md) |
| Measured CI improvements | Adopt changes supported by comparable hosted timings | [Reports and measurements](reports.md#releases-and-measurements) |

## Hardware and recovery

Record the image digest, firmware, hardware model and test date when qualifying
a workstation. Use the
[physical checklist](workstation-qualification.md#physical-hardware-checklist)
for suspend, power, displays, connectivity, media, authentication and persistence.
Retain the previous working deployment before changing channels.

Both profiles preserve their approved upstream kernel and modules. Hardware
observations belong with the tested image and device; see the
[Dell guide](dell-xps-9350.md) for model-specific checks.

## How to contribute

Start with the [development guide](development.md), choose a focused change,
and record the checks that establish its behavior. Use hosted runners for image
builds and VM qualification. Keep performance reports dated and compare queue,
evaluation, transfer, build and qualification costs before adopting an optimization.
