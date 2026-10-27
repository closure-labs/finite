# Foundation delivery from main

Foundation's `main` branch is the discovery channel, not a deployment identity.
Both personal flakes and Finite can declare
`github:closure-labs/foundation/main`. The committed `flake.lock` still records
an immutable revision and content hash. Version tags remain optional milestones;
a newer commit can have the same version as the installed source.

## Finite's acceptance policy

The scheduled Foundation updater proposes the current main commit only after
GitHub's canonical `.github/workflows/check.yml` workflow qualifies that exact
commit in a successful `push` run on `main` in `closure-labs/foundation`.
It checks the newest run and its current attempt, including a successful
`CI gate` job for the same revision. A pull-request, fork, other workflow,
older successful run, failed rerun or pending run cannot authorize a proposal.
Incomplete or inconsistent evidence fails closed. Pending or failed main CI
leaves the existing source in place; there is no fallback to a different commit.
Foundation's canonical CI policy can use its documented path-aware checks;
this is not a claim that every commit ran a full release build.

After checking source compatibility, forward ancestry and a nondecreasing
milestone version, the updater revalidates main and CI,
runs `nix flake update foundation`, and verifies that the resulting immutable
lock matches the qualified revision and hash, while its original input remains
`main`. It verifies that Foundation's dependency closure matches its own source lock,
that unrelated input closures did not change, and that main/CI remain qualified
after the lock operation. A branch
race, mismatched source, incompatible metadata or failed update restores all
three tracked files. `sources/foundation.json` records revision, hash, the
source's milestone version and upstream CI run/attempt provenance. The version
is not evidence that a release exists at that commit.

The daily workflow opens or refreshes a review proposal using the existing
short-lived, scoped Decider identity only after public validation. The existing
proposal branch name is retained to avoid parallel update PRs. No updater
merges, bypasses owner approval or replaces Finite's image, bootstrap, security
and queue checks. Upstream CI qualification is necessary, not sufficient, for
production acceptance. The checked-in source remains unchanged until an
explicitly reviewed update lands.

## Locks and runtime behavior

Build with the committed lock (`--no-update-lock-file` where supported). A bare
manual `nix flake update foundation` can select an unqualified main head; it is
candidate discovery, not production approval. Use `finite-update-foundation`
for an evidence-backed proposal, then run the normal Finite checks. The general
lock updater deliberately excludes Foundation so it cannot bypass this policy.

The image includes the exact locked Foundation source. Boot and first login do
not resolve a moving branch, and an OS update does not rewrite an existing
personal configuration. Personal updates are explicit, staged operations owned
by Foundation; direct Nix/NH update commands do not inherit the GitHub CI check.
Existing fixed revisions or tags remain usable. No `latest-release` branch or
human version bump is required to make a main commit consumable.

This change does not retroactively claim CI provenance for the previously
reviewed source: migrating an input declaration to `main` can preserve its
existing locked revision and hash. The next accepted source proposal records
its own qualification evidence.

## Rollout boundary

This implementation initially preserves the reviewed Foundation 0.5.1 lock at
`b72d5abfb1199baca777fdb34c16d30ec0b4747a` and its existing content hash. Only the
input declaration changes to main. The first successful hosted updater must
supply the full live qualification evidence before proposing a newer source.
Offline fixtures exercise the qualification and rollback contract; they are
not a substitute for that authenticated end-to-end run. The public GitHub
connector can inspect run and job evidence here, but does not expose the
workflow-metadata endpoint required by the updater's active-workflow guard.
No manual source adoption bypasses that guard.
