# Readable guest initialization diagnostics

VM acceptance preserves Foundation's structured Nix observations and exact SSH
exit status, but no longer renders every progress event into the Actions UI.
The initializer stream is sanitized and compressed directly into a private file,
with bounded parsing and
console output. Both stdout and stderr are included. The existing shell
`pipefail`, failure markers and signal cleanup remain authoritative.

Live output includes stage durations/status, ordinary output up to 32 KiB,
periodic progress summaries, and an 8 KiB non-progress failure tail. Nix error
and warning messages are decoded for display; raw activity records stay in the
full log. Oversized lines are retained in the log but omitted from console and
marker parsing. Unknown or malformed records never constitute success.

The sanitized full initializer log is retained as `home-init.log.gz` in the
existing VM artifact, with `home-init-log.json` describing whether capture
completed and the observed initialization status. The storage budget is 256 MiB
of **compressed** bytes, not uncompressed Nix progress. Independent gzip members
are written from at most 64 KiB input chunks; neither an uncompressed disk copy
nor the full stream is held in memory. The receipt records compressed bytes,
sanitized input bytes observed, the budget and any capture error.

If compressed storage is exhausted, retention stops at a complete member but
input continues to drain and stage/status parsing continues. The receipt then
says `captureComplete: false` and `captureError: compressed-byte-budget`; this
is a diagnostic evidence failure, not an invented guest OS failure. Nonzero
SSH exit status still wins through `pipefail`. For a successful guest, a separate
post-pipeline evidence check rejects incomplete capture before acceptance.
No truncated log is silently labeled complete.
Capture completion is not acceptance or publication authorization. Missing
receipts after hard cancellation remain inconclusive.

Redaction carries partial secrets across bounded read chunks before rendering,
and artifact snapshots stream rather than loading entire log files into memory.
Private capture paths, disk keys and VM disks remain outside upload paths. A
redaction or capture failure fails closed; no trusted acceptance is fabricated.
Existing diagnostic snapshots stay atomic, and small diagnostic filenames stay
unchanged. Only the potentially large initializer log is compressed. Snapshotting compressed
capture streams decompresses and redacts again before atomic export. A partial
gzip member from a hard interruption fails the snapshot closed; missing receipts
or capture-complete=false never constitute acceptance.

This change is limited to the hosted guest initializer. General Nix source-check
output filtering remains a separate follow-up; Foundation's internal-json
producer and Nix execution/resource policy are unchanged. No cache, permission,
signing, publication, or Home Manager rollback policy changes.

The first hosted queue test exposed the original uncompressed cap: 268,430,912
sanitized bytes compressed to 9,567,089 bytes. Of 1,971,614 Nix result records,
1,962,371 were routine type-105 progress updates. The producer is unchanged;
filtering these records out would lose the promised full diagnostic stream.

Offline tests cover more than 512 MiB generated compressible input without a
large input allocation, compressed-budget exhaustion, large/no-newline input, UTF-8 and secret boundaries, noisy
console caps, structured failure messages, explicit size exhaustion, exact
producer exit propagation, sanitized compressed artifacts, and existing VM
signal/timeout cleanup. Hosted exact-head contracts and subsequent VM checks
remain required; no hardware tests are needed.
