# Native runner evidence and next CI targets

PR 252 merged as `433261edd5b2eaaaa083e12e99a1e94b50bea0a5`. Its protected
[queue run](https://github.com/closure-labs/finite/actions/runs/40132204163)
passed both complete premerge profile validations. The Build Finite workflow
used 6,082 runner seconds; stage times below are nested in those jobs and must
not be added to native occupancy.

The [retained evidence](ci-native-runner-evidence-2026-10-24.json.gz) binds native
run/job/head identities, artifact inventories, stage observations and native
startup-log SHA-256 digests. Its SHA-256 is
`0dcc71e2a765b51eec82b784ad66e13dce96956cd2c41f97b6c2129a2abe27cf`. This is evidence from natural
required verification; no extra VM run was dispatched.

## A runner identity mismatch

| Profile | Native job | Startup image | Stage receipt ImageVersion |
| --- | --- | --- | --- |
| finite | [120987721923](https://github.com/closure-labs/finite/actions/runs/40132204163/job/120987721923) | 20261012.334.1 | 20261023.334.3 |
| finite-dev | [120987721975](https://github.com/closure-labs/finite/actions/runs/40132204163/job/120987721975) | 20261012.334.1 | 20261023.334.3 |

The startup section also links the matching older runner-image release. An
independent API download confirmed the startup value. The source of the
disagreement is not established. Treat environment-only runner identity as an
observation, not proof that controlled arms used the same native runner cohort.
Earlier reports and their original measurements remain preserved; their
receipt-derived image versions do not establish matched native startup images.

The installer reporter now authenticates the native job lineage as before,
then reads each successful phase job's native startup log. Reads are limited
to 8 MiB and 30 seconds per job, and only the startup section before token
permissions/workflow commands is parsed. The runner image group is distinct
from the provisioner version; later workflow-printed lookalikes are ignored.
Its release URL must agree with the image version. The reporter records the
native version and full-log hash. Missing, malformed, oversized, timed-out or
conflicting native evidence makes the sample ineligible while preserving cost.
Interrupted receipt transfers also retain native cost as ineligible evidence.

Existing frozen plans, dispatch inputs and producer receipts remain readable.
Normal qualification, signing, publication and compression defaults do not
change. The earlier stopped plan remains stopped; it gains no replacement
samples or retroactive performance claim.

## What the new resource observations show

| Profile / stage | Wall seconds | Waited-child CPU seconds |
| --- | ---: | ---: |
| finite OCI export | 181.015 | 127.919 |
| finite-dev OCI export | 485.051 | 236.108 |
| finite complete VM acceptance | 803.425 | 1,472.743 |
| finite-dev complete VM acceptance | 878.262 | 1,326.030 |

The CPU totals cover terminated, waited-for children and their reaped descendants.
Independent Docker/BuildKit work is excluded. Thus the near-zero Docker client
CPU during ISO construction does not mean Lorax was idle. Block-operation
counts remain counts, not bytes or throughput.

Native setup logs report four effective CPUs and approximately 15,989 MiB RAM
for these jobs, while the guest remains two vCPUs and 4 GiB. This makes a larger
guest allocation a concrete experiment candidate, not a demonstrated speedup.
Keep the production allocation unchanged until a predeclared controlled test
passes both profiles' fresh install and upgrade/rollback acceptance, with the
same Secure Boot, enforcing SELinux, Nix sockets and real Home Manager activation.
No additional NixOS microVM is needed to test the existing QEMU allocation.

Local OCI export also remains a measured target. Before changing compression or
transport, require exact same-build product association and complete-job costs,
including additional disk work, verification and cleanup. Do not reuse the
registry-only diagnostic as proof of a retained local-export alternative.

These recent results advance the investigation now. They do not wait for the
October 30 complete-window endpoint or authorize adoption without the existing
five warm-pair/one cold-pair correctness and performance gates. Automatic Cachix
writing and Grype database transport remain disabled.
