# Bounded GitHub metadata reads

Finite uses its existing `scripts/ci/github_api.py` GET transport with the pure
retry policy from validated XO PR #212, commit
`109656e3767982c4adf9f766d1b7d719975e37ff`.
The unchanged policy is `scripts/ci/github_retry.py`; its portable deterministic
contract is included in the existing `tests/ci/github-api.py` fixture.

## Retry bounds

A GET has at most three attempts within 45 monotonic seconds. Each transport
receives at most 30 seconds and only the budget remaining. An optional enclosing
operation deadline can shorten this budget. Wall-clock changes do not extend it.
Retry-After integer seconds or aware HTTP dates and future primary reset times
are minimum waits. Positive jitter is 0.05-0.25 seconds. Long waits defer rather
than being shortened. Missing or malformed primary reset metadata, ambiguous
headers, signals, invalid JSON and oversized responses fail closed.

403 requires explicit throttle headers; permission failures and unrelated 4xx
are terminal. A 429 without a server delay requires at least 60 seconds, so the
45-second reader defers it without another GET. Exhausted quota never launches
the separate closed-PR provenance discovery fallback. Other existing transient
association failures retain that bounded, independently validated discovery path.
Only validated numeric rate metadata and sanitized request identity are logged;
response bodies, arbitrary headers and credentials are not logged.

The helper does not retry mutations, replace credentials, increase quotas,
change permissions or cache an authority conclusion. Final fresh main, complete
ledger, exact-head review, membership, repository permission and revocation
checks remain authoritative.

## Bounded immutable-byte reuse

Each security-admission operation uses the existing 64-entry/16-MiB proposal-byte
cache. A complete Git tree at a full main commit SHA can authenticate already-read
local proposal bytes: regular blob mode, exact path and byte size, recomputed Git
blob hash, and strict JSON parsing must all match. Only those bytes are seeded for
that exact repository/path/commit binding. Cache exhaustion uses the original
read path; scope exit releases the bytes. A new operation rereads current state.

This avoids fetching the same current-main proposal body again while retaining
all live reads. The twelve-decision, one-page, one-reviewer fake-API fixture runs
the actual provenance and authority functions and records:

| GET boundary | Cache disabled | Enabled |
| --- | ---: | ---: |
| Total | 137 | 125 |
| Immutable proposal bodies | 36 | 24 |
| Fresh main references | 14 | 14 |
| Complete ledger trees | 2 | 2 |
| Review inventories | 1 | 1 |
| Super Admin inventories | 3 | 3 |
| Selected membership reads | 3 | 3 |
| Selected permission reads | 3 | 3 |

These are deterministic fixture counts, not a production traffic trace or a
measured hosted speedup. The incident motivating the change was baseline
41153486375: an upgrade metadata HTTP502 followed by a rate-limited promotion
HTTP403. Both were recovered through scoped native job retries with all gates
retained. The reduction lowers repeated reads; it cannot guarantee that a shared
installation quota is always available.

Full Nix and hosted workflow validation belongs to CI. Lightweight fixtures use
fake clocks and API responses: no network calls or real retry sleeps.

Source: [validated XO helper and contract](https://github.com/closure-labs/xo-nixpkg/blob/109656e3767982c4adf9f766d1b7d719975e37ff/docs/github-retry-contract.md).
