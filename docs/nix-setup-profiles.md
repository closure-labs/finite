# Explicit Nix setup profiles

Every `setup-nix` call declares `job-profile`: `controller`, `checks`, `image`,
or `vm`. The role describes the workload rather than its GitHub job ID. Missing
or unknown roles fail before Nix setup. Only the existing Build Finite checks
caller declares `checks`; all other current callers retain non-checks behavior.

The separate `cache-profile` override stays `auto`, `checks` or `sources`.
`auto` follows the declared job profile. Existing experiments can still force
checks snapshots or source-only restoration without changing their workload
role. Existing `cache-mode` overrides and public optimized-cache flags remain.

| Mode | Snapshot restore | Source-only restore |
| --- | --- | --- |
| `none` | Never | Never |
| `baseline` | Always | Never |
| `optimized` | Checks cache profile, or auto with checks role | Other profiles |
| Default, optimized public flag true | Checks cache profile, or auto with checks role | Never |
| Default, optimized public flag false | Always | Never |

Snapshot writing still requires the checks role, canonical repository, main ref
and push/schedule/manual event. Source-only writing keeps its existing trusted
main restriction. Cache keys, restore prefixes, source paths, size bounds,
timeouts, permissions, credentials, public substituters and upstream action pins
are unchanged. Caches remain transport hints; they cannot replace fresh
authority, signature, source, digest or qualification checks.

The rollout maps every existing call to its previous behavior. Tests cover the
restore truth table, trusted writer matrix, invalid roles, all workflow calls,
existing overrides and absence of job-name coupling. No measured speedup is
claimed, and no cache or benchmark is dispatched by this refactor.
