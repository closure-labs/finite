# Doppler OIDC canary pilot

This manual pilot is independent of release qualification and retrieves no
production credentials. It executes inline workflow code without checking out
or executing repository scripts. The fetch action is pinned to reviewed v2.0.0
commit `451892f16195f9ac360e1a5bcbf0b5fd0e957534`.

GitHub-side rollout is deployed by [PR #154](https://github.com/closure-labs/finite/pull/154).
[Claims-only run38452109711](https://github.com/closure-labs/finite/actions/runs/38452109711)
passed at `31e47a59f456caceaacda75557c7971eba3a172d`; the public claims below were
observed exactly. Doppler authentication remains untested because no workspace exists.

## Configure the two control planes

1. GitHub environment `doppler-pilot` is configured with deployment branches limited
   to `main` (policy ID `62941382`), administrator bypass disabled, and no secrets.
   Do not add signing or other production secrets. Dispatch
   **Doppler OIDC canary pilot**, mode `claims-only`, from `main`. Only an explicit
   allowlist of public OIDC claims is printed and retained in the job summary;
   the assertion is not retained. No Doppler variables are needed for this mode.
2. No Doppler workspace exists yet, as confirmed by the owner on 2026-10-13.
   Create one and confirm Team or Enterprise service-account identity
   entitlement. Create a dedicated pilot project/environment/config containing
   only `FINITE_DOPPLER_PILOT_CANARY`, a disposable random value with masked
   visibility. No secret references into production configs. Because the action
   fetches the entire config, selecting one output is not access control.
3. Create a dedicated service account with read-only secret access confined to
   this pilot project/environment. Grant no workplace management privileges and
   no access to audit, signing, release or other repositories' configurations.
   Create a GitHub OIDC identity with the exact rules below. All configured
   claims must match; do not use wildcard alternatives.
4. Set these GitHub **repository variables**, not secrets or environment-only
   variables: `DOPPLER_PILOT_IDENTITY_ID`, `DOPPLER_PILOT_PROJECT`, and
   `DOPPLER_PILOT_CONFIG`. The denial job deliberately runs without an environment
   and needs the nonsecret identity ID. Do not store a Doppler API token.

| Claim | Exact required value |
| --- | --- |
| Issuer/provider | `https://token.actions.githubusercontent.com` |
| `aud` | `https://github.com/closure-labs` |
| `sub` | `repo:closure-labs@256683018/finite@1293375784:environment:doppler-pilot` |
| `repository_id` | `1293375784` |
| `repository_owner_id` | `256683018` |
| `ref` | `refs/heads/main` |
| `event_name` | `workflow_dispatch` |
| `workflow_ref` | `closure-labs/finite/.github/workflows/doppler-pilot.yml@refs/heads/main` |

Match the actual public probe claims before enabling fetch. This repository uses
immutable subjects; do not replace its subject template with an older example.
The pilot is a direct workflow, so use `workflow_ref`, not `job_workflow_ref`.
A future reusable-workflow integration needs its own exact `job_workflow_ref`
condition and separately scoped identity. Environment subjects do not contain
the branch, so retain the independent `ref` rule.

## Run and interpret validation

Dispatch mode `validate` from `main`. The protected canary job verifies expected
public claims, retrieves the canary using OIDC, and checks presence without
printing its value. The action does not inject secrets into subsequent steps;
only the named canary output is passed to its consuming step.

Two negative checks submit genuine GitHub assertions to Doppler's authentication
endpoint: wrong audience in the trusted environment, then correct audience from
the same workflow without the trusted environment. They require HTTP401/403.
A network error, timeout, malformed request response, or unexpected success is
a failure, not proof of denial. Response bodies and tokens are discarded, and
negative checks never fetch secrets. Running the authorized fetch first avoids
mistaking an unconfigured identity for working trust restrictions.

These checks prove audience/environment rejection, not every trust condition.
Before adopting production credentials, complete backend rejection checks for
wrong workflow, ref and repository as well. Use a reviewed temporary canary-only
probe in each wrong context that **actually calls Doppler** with a genuine JWT
and the same identity ID; require HTTP401/403 and retain only context/status/run
links. For a wrong-ref test with the same environment subject, use a disposable
test environment/identity mirroring the production rules but allowing the test
branch through GitHub; keep Doppler's exact-main rule. Never loosen an existing
production environment. A skipped job, environment rejection, forged JWT or
permission denial in GitHub alone does not prove Doppler's claim enforcement.
Delete temporary probes/identities after recording evidence.

Record exact workflow revision/run, observed public claims, positive presence,
negative status codes, step duration and log review. Do not upload action output
files, environments, assertions, API responses, or canary material. Masking is
not an authorization boundary, and this pilot does not print the canary to test
masking. Inspect logs for accidental disclosure without copying values into
reports. Claims-only success does not establish Doppler access; canary success
does not authorize production rollout.

The fetch step has a two-minute deadline; probes use 15-second request deadlines
and one-minute step deadlines. No Nix/toolchain installation or image work is
needed. OIDC removes a static Doppler bootstrap token but does not rotate the
underlying App or Cosign keys. Keep production environment secrets and existing
signing controls until a separately reviewed rollout and rollback are ready.

Rollback: stop dispatching the pilot, revoke its Doppler identity/service-account
access, and remove the three repository variables. Existing release workflows
and credentials are independent of this pilot.

Sources: [reviewed action](https://github.com/DopplerHQ/secrets-fetch-action/tree/451892f16195f9ac360e1a5bcbf0b5fd0e957534),
[Doppler identity rules](https://docs.doppler.com/docs/service-account-identities),
[GitHub OIDC claims](https://docs.github.com/en/actions/reference/security/oidc).
