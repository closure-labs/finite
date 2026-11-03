# Shared public CI options

Nix setup and cache restore already use the shared `setup-nix` composite action.
Each of its 36 calling workflow files now passes GitHub's native public `vars`
context as `FINITE_CI_VARS: ${{ toJSON(vars) }}` instead of copying seven variable
bindings. The existing `ci-options.py` resolver selects only the six declared
boolean switches and ISO channel selector; unrelated public variables are never
exported or logged. It rejects duplicate JSON members, non-object configuration,
non-string declared values and invalid options. No variable is evaluated as code.
Explicit job/step environment overrides retain precedence, including benchmark
channel overrides. Source-proof mode retains its separate checks-job binding.

Bootstrap still precedes cache selection, then SecretSpec validates the resolved
public options. Cache keys, restore/save conditions, writer restrictions, workload
profiles, substituters and credentials are unchanged. No new configuration variable
or repository setting is required. The change removes 216 repeated YAML bindings;
it makes no measured runtime or cache-hit improvement claim.

Tests compare all 729 boolean/empty configurations across four channel selectors
against the legacy environment interface, exercise malformed/injected inputs,
and retain existing cache-selection/writer truth tables and workflow integration
checks. Review must include the job/step overrides and pre-setup consumers.

GitHub documents the public configuration context and native JSON serialization
in its [contexts reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts).
