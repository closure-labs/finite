# Readable guest initialization diagnostics

VM acceptance preserves Foundation's structured Nix observations and exact SSH
exit status, but no longer renders every progress event into the Actions UI.
The initializer stream is captured in a private file, with bounded parsing and
console output. Both stdout and stderr are included. The existing shell
`pipefail`, failure markers and signal cleanup remain authoritative.

Live output includes stage durations/status, ordinary output up to 32 KiB,
periodic progress summaries, and an 8 KiB non-progress failure tail. Nix error
and warning messages are decoded for display; raw activity records stay in the
full log. Oversized lines are retained in the log but omitted from console and
marker parsing. Unknown or malformed records never constitute success.

The sanitized full initializer log is retained as `home-init.log.gz` in the
existing VM artifact, with `home-init-log.json` describing whether capture
completed and the observed initialization status. A 256 MiB sanitized-log budget fails
explicitly if exceeded; it never silently labels a truncated log complete.
Capture completion is not acceptance or publication authorization. Missing
receipts after hard cancellation remain inconclusive.

Redaction carries partial secrets across bounded read chunks before rendering,
and artifact snapshots stream rather than loading entire log files into memory.
Private raw paths, disk keys and VM disks remain outside upload paths. A
redaction or capture failure fails closed; no trusted acceptance is fabricated.
Existing diagnostic snapshots stay atomic, and small diagnostic filenames stay
unchanged. Only the potentially large initializer log is compressed.

This change is limited to the hosted guest initializer. General Nix source-check
output filtering remains a separate follow-up; Foundation's internal-json
producer and Nix execution/resource policy are unchanged. No cache, permission,
signing, publication, or Home Manager rollback policy changes.

Offline tests cover large/no-newline input, UTF-8 and secret boundaries, noisy
console caps, structured failure messages, explicit size exhaustion, exact
producer exit propagation, sanitized compressed artifacts, and existing VM
signal/timeout cleanup. Hosted exact-head contracts and subsequent VM checks
remain required; no hardware tests are needed.
