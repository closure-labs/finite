# Bluefin update recipe fixture

`bluefin-update.just` is the workstation's installed
`/usr/share/ublue-os/just/update.just`, captured on 2026-10-21. SHA-256:
`f9f3a9844e1a9c4e934f3bbb529a9857550ffc768de5ac2853a6226aabddaa8c`.

The update tests run real Just against this unmodified recipe, substituting only
the Bash interpreter, rpm-ostree policy path and Brew executable path in a
temporary copy. OS, Flatpak, Brew and Foundation commands are controlled fixtures.
Production delegates to the installed Bluefin recipe; it neither reads nor
extracts this fixture's body.

Refresh and requalify this fixture when the image's upstream updater changes.
The current qualified recipe is one Bash script with bare update commands and
conditional discovery/ownership checks. Bash's `errexit` exemptions still apply
to those conditions; the marker does not prove arbitrary future interpreters or
recipes preserve this contract.
