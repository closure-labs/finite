# Direct PR lifecycle authority events

Handle `opened`, `synchronize`, `reopened` and `ready_for_review` directly in the
trusted main authority workflow using GitHub's native `pull_request_target`
event, limited to PRs targeting main. Remove their empty collector job and its
completion fanout. Base-retarget `edited` events remain covered; a job guard skips
title/body-only edits because those fields are not authority inputs. Review-body
edits remain covered.

The collector still handles review submission/edit/dismissal and merge-group
requests. Those events must not execute credentialed code from a candidate tree.
Incoming and historical secret scans, native execution admission, exact-head
human findings acceptance and merge-group integration checks remain separate.
No native protection rule or repository setting is changed.

The direct route checks out main with no persisted credentials. Discovery uses
only the native event's repository/base/PR/source tuple and live PR metadata;
the existing credentialed worker reauthenticates the exact current head, reviews,
team permissions, risk packet and queue tree. Native target-run API metadata
names the PR source branch/SHA, despite the workflow executing in base context;
fixtures cover this distinction and reject an incorrect source/event binding.
The scheduled and manual recovery routes and their existing freshness checks
remain unchanged. A target event grants neither findings acceptance nor merge
approval. Fork code, local actions and artifacts are not executed by this route.

## Observed fanout and limits

The 100-run inventory read on 2026-11-03 included 32 admission completion
callbacks, nine event-driven authority runs and nine collector runs (four PR
lifecycle, three review, two merge-group). Native examples are admission runs
[41583773365](https://github.com/closure-labs/finite/actions/runs/41583773365)
and [41565729381](https://github.com/closure-labs/finite/actions/runs/41565729381),
and review collector
[41583903830](https://github.com/closure-labs/finite/actions/runs/41583903830).
This is a bounded inventory, not a representative cost benchmark.

For each replaced PR lifecycle event, the new route removes one collector job
and its downstream admission callback; authority execution itself remains.
Already-skipped callbacks consumed no runner job, so workflow-count reduction
must not be presented as an equivalent billed-time saving. Review and queue
fanout remain for now. No measured speedup is claimed. Hosted PR tests exercise
the code/contracts; the changed native event route takes effect only after review
and merge, so post-merge observation is still required.

GitHub documents base-context execution in its
[event reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request_target)
and cautions against mixing privileged target/run triggers with untrusted code in
[secure use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
The implementation follows that separation instead of treating event identity
or an empty collector's success as human authority.
