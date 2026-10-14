# Nix workflow setup and resource audit

Reviewed on 2026-10-14. All jobs currently use `ubuntu-24.04`. Every host job
that invokes Nix installs the pinned Determinate Nix action before using it.
The shared setup now measures CPU affinity, cgroup-v2 CPU quotas and memory
limits, and physical RAM before installation. Setup verifies the selected
settings and the Determinate client afterward without printing token-bearing
configuration.

## Resource policy

Reserve 1 GiB for the OS and daemon, budget 3 GiB per simultaneous builder,
and limit builders to the available CPUs. Divide the CPU budget among builders
with `cores`; the product of jobs and cores never exceeds the CPU budget.
Evaluation uses up to one thread per 2 GiB after the same reserve and enables
Determinate's parallel evaluator. These are planning allowances, not a promise
that every derivation fits that memory budget. A builder's own parallelism may
also differ from the hint supplied by Nix.

| Available resources | max-jobs | cores per job | eval-cores |
| --- | --- | --- | --- |
| 4 CPUs, 16 GiB | 4 | 1 | 4 |
| 2 CPUs, 8 GiB | 2 | 1 | 2 |
| 16 CPUs, 64 GiB | 16 | 1 | 16 |
| 16 CPUs, 16 GiB | 5 | 3 | 7 |
| Qualification guest: 2 CPUs, 4 GiB | 1 | 2 | 1 |

Actual settings use measured memory, so machines just below a table boundary
may receive a smaller budget. Parallel evaluation applies to supported commands
and explicit parallel evaluation expressions; it does not automatically
parallelize every scalar `nix eval --raw` expression. Builders and evaluation
threads are different controls, and two overlapping Nix processes can still
compete for resources. Existing command sequencing remains unchanged.

## Workflow coverage

| Workflows/jobs | Setup |
| --- | --- |
| Build Finite: main reconciliation and full checks | Shared Determinate setup; conditional reconciliation installs only when used |
| Build one image | Shared setup before pinned tool realization and payload evaluation |
| Candidate security and promotion | Shared setup before lightweight release/shell tools |
| Published-image security, repository audit, upstream health | Shared setup before Nix tooling |
| Bluefin resolution, update validation and recovery | Shared setup in each independent job |
| Determinate, flake and Home Manager updates; dependency queue | Shared setup before updater tools |
| Qualified release evidence and rescan | Shared setup; signing job has its own pinned Cosign installer |
| Image-tools benchmark | Same resource detector, pinned Determinate installer and verification, with no Actions store cache |
| VM acceptance and candidate qualification | Host tools use apt and the pinned CLI; guest tests use the image's installed Determinate Nix and budget from guest resources |
| ISO, kernel checks, RPM diagnostics, desktop evidence, Doppler | Host steps do not invoke Nix; no additional installer is needed |

The guest verifies Nix initialization through the existing policy/state/daemon
unit checks. Its temporary test-session configuration preserves inherited
settings and applies the measured guest budget to Home Manager commands. It
does not install a second Nix or change the workstation's persistent policy.

## Validation

Focused tests cover public/private/larger-runner and VM budgets, nested cgroup
limits, ignored configuration, wrong clients and Nix setup ordering across all
workflows. The benchmark retains identical installer configuration in both
arms. Hosted checks exercise the actual installed runner configuration.

Sources: [GitHub runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
and [Determinate configuration reference](https://manual.determinate.systems/command-ref/conf-file.html).
