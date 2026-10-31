# Bounded delivery metadata discovery

The remaining direct paginated metadata readers now use the existing
`github_api.get_json` transport, which owns the three-attempt/45-second policy,
server not-before handling and remaining-time transport cap. There is no second
retry loop, mutation retry, credential fallback or authority-verdict cache.

| Reader | Scope |
| --- | --- |
| Qualification reuse and ISO retention | One discovery operation |
| Preserved predecessor lookup | One operation, including nested qualification and origin-artifact metadata |
| Image-inventory reuse | One discovery operation; replaces the old separate retry loop |
| Release artifact listing | One bounded listing, inheriting an enclosing operation when present |
| CI-cache retention listing | One complete bounded inventory before a deletion plan can exist |

Each discovery shares a 150-second monotonic deadline and at most 120 logical
GETs. Each GET retains the transport's lower 45-second budget and at most three
attempts; transport timeouts shrink to remaining time. Nested readers share the
parent counters and deadline. A later operation starts fresh and re-reads its
metadata. The scope stores counters only, including on failure; it stores no
responses, permissions or authority conclusions.

Artifact, job and cache listings use fixed relative page requests with 100 items
per page and at most 20 pages. They require a consistent native total count,
positive unique IDs, complete coverage and valid page shapes. A page, read or
deadline cap rejects the partial inventory. No arbitrary `Link` target is followed.
An exactly full final page needs no extra empty-page GET when its count proves
completion. Cache deletion selection still performs its existing independent
identity/count checks, and DELETE commands remain single attempts.

The enclosing discovery clock can expire during separately bounded archive
transfer or tool preparation; the next metadata read then fails closed rather
than starting another full budget. Binary archive downloads retain their
existing byte/digest/timeout rules. This change does not retry HTTP mutations,
change freshness checks or modify final live main/review/ledger/member checks.
The operation cap is a rejection boundary, not permission to accept incomplete
qualification evidence or a false healthy cache result.

Other direct `gh api` uses in this path are binary artifact downloads or
POST/DELETE operations and remain separate. Source-update HTTP transport in
`http-get.py` already has its own 150-second enclosure and HTTPS credential
boundary and also handles non-GitHub downloads; this PR does not replace that
interface. Existing cost, health, publication and authority JSON readers already
use the shared GET transport. No broad repo-wide transport rewrite is included.

Fixtures cover two-page completion, exact-full-page call counts, empty and
truncated pages, changing counts, duplicate IDs, page/read/deadline exhaustion,
shared nested budgets and reset on exceptions. Actual transport fixtures verify
502 recovery, terminal ordinary 403s and server throttle delays that cannot fit
inside the enclosing budget. No hosted latency or request-volume improvement is
claimed beyond those deterministic bounds and call counts.
