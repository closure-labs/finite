# Maintainer decision App

CL Decider is the GitHub App owned by closure-labs for human decision proposals,
authority checks and approved-build resumes. It has no paid service or trial and
is separate from StepSecurity. FlakeHub, cl-sec-audit and StepSecurity Actions
Security do not provide this decision authority. Keep cl-sec-audit read-only.

For another installation, GitHub requires an interactive owner registration before its manifest conversion
API can create an App; a normal authenticated REST request cannot register one
without that browser step. Use
https://github.com/organizations/closure-labs/settings/apps/new and these settings:

- Name: Finite Maintainer Decisions (or another available name).
- Homepage: https://github.com/closure-labs/finite.
- Webhook: inactive; no webhook receiver or hosted service is needed.
- Repository permissions: Administration **read**, Actions **write**, Checks
  **write**, Contents **write**, Issues **write**, Pull requests **write**.
- Organization permissions: none. Subscribe to no webhook events.
- Installation: **Only on this account**, select **only finite**.

The reviewed machine-readable manifest is
`automation/github/apps/maintainer-decisions.json`. Administration read permits
checking each reviewer's current effective repository role. Actions write permits
resuming retained candidates. Checks write provides the required check's distinct
App identity. Contents/PR write creates bot-authored proposals; Issues write maintains
the single health issue. No Workflows write, secrets access, or signing key access.

CL Decider is now installed (App ID `5384448`, bot `cl-decider[bot]`). Its
organization values are `DECIDER_CLIENT` (client ID, variable or secret) and
`DECIDER_KEY` (PEM secret). Workflows map these into SecretSpec's canonical
`FINITE_REVIEW_CLIENT_ID` and `FINITE_REVIEW_PRIVATE_KEY` keys, with no duplicate
private key storage. Repository-scoped tokens select only finite.

For another installation, generate a key and store it directly with:

```sh
gh secret set DECIDER_KEY --repo closure-labs/finite < /path/to/app-key.pem
gh variable set DECIDER_CLIENT --repo closure-labs/finite --body CLIENT_ID
gh variable set FINITE_REVIEW_APP_ID --repo closure-labs/finite --body NUMERIC_APP_ID
gh variable set FINITE_REVIEW_BOT_LOGIN --repo closure-labs/finite --body 'app-slug[bot]'
```

Do not paste the private key into chat or commit it. SecretSpec's standalone
`review-app` scope resolves the key only for token generation. Tokens must be
short-lived and restricted to this one repository. The App does not approve PRs.
A current human maintainer/admin approves the bot-authored PR's exact head.

Before cutover, verify the App's check on an ordinary PR, a proposed decision,
a changes-requested review, a new head push, and the merge queue. Bind the required
`Maintainer decision authority` check to **this App's numeric integration ID**,
not GitHub Actions. Keep existing enforcement and the release environment's human
reviewer until this check is healthy and the initial human baseline is merged.
Never change a policy file or repository variable to simulate that approval.

StepSecurity Community settings: use Harden Runner on GitHub-hosted runners with
`egress-policy: audit`. Do not enable Enterprise GitHub Checks, workflow run
policies, Actions governance, private/self-hosted coverage, or a trial. Its optional
Community remediation PRs are separate suggestions, reviewed like other code.

Audit mode does not impose a repository egress allowlist. StepSecurity's global
blocklist still blocks known malicious destinations even in audit mode; this is
an upstream runtime protection, separate from human decisions on CVE findings.
See the [Harden Runner feature documentation](https://github.com/step-security/harden-runner#community-free).
No policy-store, API-key, Enterprise checks, or trial settings are configured.
