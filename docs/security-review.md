# Review security findings

CL Decider opens a pull request when native image scans need a human decision.
The proposal brings both Finite profiles together with a findings summary,
vulnerability links and the complete evidence packet.

Only a current member of **Super Admins** with maintain or admin repository
access can authorize a decision. Approval applies to the exact reviewed PR head.

## Review a decision PR

1. Open the CL Decider PR and read its proposed disposition and rationale.
2. Review new or worsened findings, affected components, severity, exploitation
   status and shipped-file exposure. Follow the advisory links and immutable
   evidence packet for detail.
3. For acceptance, use **Files changed → Review changes → Approve → Submit
   review**. Approve the latest head after any push. The App verifies your
   current team membership and repository role.
4. Let the required **Maintainer decision authority** and **CI gate** checks
   finish. The merge queue then integrates the approved proposal.

An accepted decision lets covered builds continue unattended. New or worsened
risk opens another decision; unchanged or reduced risk carries forward.
Acceptance has no renewal timer. Current scan health, signatures and exact-image
boot qualification are checked independently for every publication.

## Find a waiting decision

Check the PR's latest checks first. A pending or failed authority check
includes its reason; confirm that an eligible reviewer approved the latest head.
A failed CI check links to the failing job. CL Decider's **Maintainer decision pipeline health** issue reports stale
published-image audits and decisions waiting beyond their monitoring window.

The [implementation status](ci-maintainer-decisions.md#bootstrap-and-cutover)
tracks the one-time activation and release transition. The baseline was approved
in [PR 188](https://github.com/closure-labs/finite/pull/188); the policy activation
is tracked in [PR 191](https://github.com/closure-labs/finite/pull/191).

## Change a decision

Use **Reconcile maintainer decisions** on `main` to propose a rejection or
revocation with a rationale. Revocation withdraws permission for future
publication. It receives the same Super Admin review as acceptance.

For payload identities, live authority checks, risk comparisons and recovery,
read the [security decision contracts](automation/security-decisions.md). App
permissions and Community scanner settings are in the
[App guide](maintainer-decision-app.md).
