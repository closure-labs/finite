# Publication resume artifact reader

Publication resume now delegates its byte transfer and ZIP size/digest
authentication to `archive_read.single_archive_reader`. This is an explicitly
bounded, uncached, single-attempt adapter. It does not inherit the release
reader's retries or 90-minute deadline, and does not affect qualified ISO
transfer, progress fallback or metadata discovery.

The caller retains a 64MiB archive cap, a 180-second timeout, exactly three
selected filenames and a positive 4MiB bound on each selected member. No archive
path is extracted. Unrelated entries remain ignored. Missing, duplicate,
oversized or corrupt selected content fails closed. The shared authenticator
also requires downloaded length to equal native `size_in_bytes`; inconsistent
native metadata is rejected before parsing. The child has an archive-size file
limit so a transfer cannot grow beyond the caller's cap.

Native repository/workflow/main/source/run/attempt/job/step and artifact bindings
remain in `origin_metadata`. Candidate digest, labels, current input identity,
ancestor source and publisher authentication remain in the resume controller.
The three returned byte strings and all downstream receipts are unchanged.
Resume still requires fresh security and qualification and never authorizes
promotion merely by reading original build evidence.

Focused fixtures cover valid receipts, native producer substitutions, wrong
attempt/source, malformed metadata, one-attempt timeout/HTTP errors, cleanup,
size/digest mismatch, malformed ZIPs, duplicate/missing members, compressed
oversized members and ignored traversal-looking unrelated entries. Existing
release-origin/handoff tests exercise the unchanged default reader separately.
