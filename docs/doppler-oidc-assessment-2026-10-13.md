# Doppler OIDC assessment for Finite

Decision: suitable for a limited CI/CD pilot, especially for organization-wide
secret administration. Keep the current release independent of adoption.
The user authorized the pilot rollout after this assessment. GitHub preparation
is underway; live Doppler integration remains unvalidated. The user confirmed
that no Doppler workspace exists. No production secret values were read, exported
or changed.
Great CTO security/integration review agrees with this scoped recommendation.

## Current build failure

[Run38439778084](https://github.com/closure-labs/finite/actions/runs/38439778084)
at `b274129fc76f2bdf588b4b312d83af4759e0d1a7` passed source checks, the standard
image build and the security-policy job. Candidate:

`ghcr.io/closure-labs/finite@sha256:60b12153f6c3db4152225e6213ff5ae95971190cca87920b969a848b5fa423ef`

Signing job115457097464 failed with `reading key: invalid pem block`. Its logged
`COSIGN_PRIVATE_KEY` environment entry is empty. GitHub metadata confirms that
the named secret exists in both protected environments; metadata cannot establish
its contents. This failure therefore does not prove that the stored PEM is corrupt.

The `build.yml` publication caller passes no secrets, and `publication.yml`
declares no workflow-call secret contract. GitHub's
[current reusable-workflow documentation](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows)
requires explicit forwarding even for an environment secret. Environment values
then take precedence in the job referencing that environment. This explains the
empty value observed in the signer.

Repair sequence: declare the named secret as required, pass only that name from
the caller, retain `image-signing` on the isolated signer, and add a nonempty/key
format and public-key-match preflight that emits no private material. A required
workflow-call declaration checks forwarding, not whether the value is nonempty.
Do not use blanket secret inheritance or move key access into build/scan jobs.
After focused and hosted validation, resume this exact manual-origin candidate;
reuse authenticated security evidence while fresh. If evidence expires, rescan
this digest. Another image build is not indicated by this signing-wiring failure.
VM qualification and promotion were skipped and remain required.

## Benefits and limits

Doppler can exchange a GitHub job's OIDC assertion for a short-lived service
account token. There is no permanent Doppler bootstrap token to put in GitHub.
Service-account identities require a Team or Enterprise subscription; the
organization's entitlement remains unverified.
[Identity documentation](https://docs.doppler.com/docs/service-account-identities)

The reviewed action is v2.0.0, pinned at
`451892f16195f9ac360e1a5bcbf0b5fd0e957534`. It runs directly on Node24 without a
Nix, Docker or Doppler CLI installation. It adds network authentication and fetch
calls, so measure pilot overhead rather than claiming a speed improvement.
The fetch implementation has conditional retries but no explicit HTTP timeout;
set a one-to-two-minute step timeout.
[Action definition](https://github.com/DopplerHQ/secrets-fetch-action/blob/451892f16195f9ac360e1a5bcbf0b5fd0e957534/action.yml),
[HTTP implementation](https://github.com/DopplerHQ/secrets-fetch-action/blob/451892f16195f9ac360e1a5bcbf0b5fd0e957534/doppler.js)

It fetches the whole selected config and exposes all retrieved secrets as step
outputs. There is no secret-name filter. Leave `inject-env-vars` disabled and map
only named outputs into consuming steps. This reduces accidental propagation;
real access isolation must come from Doppler permissions and config contents.
Masking excludes metadata and values marked unmasked. Do not copy examples that
print environments, persist tokens, or upload fetched values.
[Reviewed entry point](https://github.com/DopplerHQ/secrets-fetch-action/blob/451892f16195f9ac360e1a5bcbf0b5fd0e957534/index.js)

OIDC does not rotate the underlying Cosign key, GitHub App PEM or GitHub personal
token. Rotation depends on the target integration and lifecycle. Cosign rotation
also needs a client trust transition; moving storage should preserve the key.
Doppler retrieval still delivers plaintext to the authorized runner; it is not
non-exportable hardware-backed signing.
[Rotation requirements](https://docs.doppler.com/docs/secrets-rotation)

## Trust policy for this repository

Live GitHub settings use immutable subjects, with prefix:

`repo:closure-labs@256683018/finite@1293375784`

Do not replace the repository's OIDC subject template merely to copy an example.
For an eventual image signer, expected claims to validate in a canary are:

| Claim | Required value |
| --- | --- |
| Issuer | `https://token.actions.githubusercontent.com` |
| Audience | `https://github.com/closure-labs` |
| Subject | `repo:closure-labs@256683018/finite@1293375784:environment:image-signing` |
| Repository ID | `1293375784` |
| Owner ID | `256683018` |
| Ref | `refs/heads/main` |
| Reusable workflow | `closure-labs/finite/.github/workflows/publication.yml@refs/heads/main` |
| Events | Explicitly allow only supported push, schedule and manual publication events |

The action requests the default GitHub audience. Environment subjects omit the
branch, so the separate ref condition matters. Verify actual nonsecret claims in
a pilot; never log the raw JWT. Preserve main-only environment restrictions and
the release environment's designated reviewer. Grant `id-token: write` only to
consuming jobs; reusable callers must permit the corresponding token permission,
while builders/scanners retain explicit permissions without OIDC access.
[GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc)

Use separate service accounts and exact identities per repository and security
boundary. Several identities on one broadly privileged service account do not
provide separate secret privileges. Avoid organization-wide wildcard trust.
[Service-account access model](https://docs.doppler.com/docs/service-accounts)

## Suggested sequence

1. Repair and verify the existing signing-secret boundary independently.
2. Confirm Doppler entitlement; create a dedicated pilot config containing only
   a disposable canary, with read-only service-account access and a main-only
   pilot environment. Store its identity ID as a GitHub variable.
3. Pin the reviewed action SHA; use OIDC, explicit project/config, no global env
   injection and a bounded timeout. No production secrets, Nix build or image
   scan is needed for this pilot.
4. Test allowed access and rejection of wrong branch, repository, environment
   and workflow. Record masking and failure/timeout behavior without logging
   credentials. A GitHub-side denial alone does not prove Doppler denied access.
5. If successful, trial the read-only audit App job. Keep its App permissions
   unchanged and installation tokens repository-scoped. Keep `SECAUDIT_CLIENTID`
   as a variable. Central storage does not reduce the raw shared App key's scope.
6. Consider signing and release last, with separate identities/config access,
   preserved GitHub environment gates, existing-key public-key verification and
   an explicit rollback procedure. Do not fetch secrets in ordinary builds,
   scans or PR checks that do not consume them.

Acceptance: exact authorized job succeeds; unauthorized contexts cannot fetch
canary material; no secret/token leakage; bounded failure latency; existing
signing/environment protections remain effective. Doppler workspace access and
a successful canary are prerequisites to claiming production readiness.
