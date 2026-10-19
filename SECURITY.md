# Security

Use GitHub's private vulnerability reporting for exploitable issues:
[report a vulnerability](https://github.com/closure-labs/finite/security/advisories/new).
Include the affected image digest/profile, reproduction steps and impact.
Do not post credentials, private keys or personal workstation data in public issues.

Published channels use native image scanning, signature verification and
exact-image boot qualification. CL Decider presents findings for human review;
Super Admins with maintain/admin access authorize the exact decision PR head.
See [security review](docs/security-review.md) for the workflow and activation
status, and [CI security controls](docs/ci-and-releases.md#image-vulnerability-gate)
for scan health and publication requirements.

Use [Install and update](docs/installation.md#update-your-system) to keep your
system and personal applications current. Finite is maintained as a personal
desktop project; response and patch timing depend on maintainer availability.
