# Qualification source dependency boundaries

FINite currently binds the complete qualification source context before reusing
VM acceptance. Its predecessor ISO reader projects out only `local-vm.sh` and
itself. This is intentionally conservative: a publication-controller change can
invalidate a retained pristine ISO even when its construction did not change.

Do not expand that projection by subtracting filenames from the old context.
The old context is not a complete standalone ISO-generation contract. For
example, it records the CLI lock but not `sources/bluebuild-cli.pub`, and omits
the `setup-cosign` action and its download settings. The actual tool executables,
workflow arguments, installer modes, and generated inputs matter too.

## Stage one: observation only

`scripts/ci/qualification-dependencies.py` emits a versioned source inventory
with candidate domains:

- **image**: shared build helpers and shipped guest integration;
- **iso-generation**: pristine installer construction, not VM personalization;
- **vm-acceptance**: guest preparation, current acceptance and observation;
- **policy**: trust roots, security policy and evidence/publication checks;
- **host-controller**: orchestration, eligibility and reporting.

Domains overlap deliberately. Shared CLI locks and trust roots are not solely
ISO inputs. `qualify.sh` and the qualification workflow contain generation
arguments as well as acceptance control, so they remain generation candidates.
No domain is an exclusion from the current image identity.

The inventory covers the current qualification collector, recursively inventories
its helper/installer/guest directories, and supplements known transitive source
inputs. Only exact reviewed filenames receive narrower labels. Unknown/new
inputs retain **all five domains**. Missing reviewed inputs fail report creation
rather than silently disappearing. Content, executable status and internal file
symlink target text are bound; external/dangling/directory symlinks are rejected.
Host-generated Python bytecode is ignored.

Like the qualification scripts it loads, the reporter executes trusted checkout
code; it is not a sandbox for hostile repository contents.

The phase job retains `<profile>-<phase>-source-boundaries.json` in its existing
seven-day phase artifact. Report creation has a one-minute timeout, is best-effort, and cannot turn a failed
acceptance into success or stop an otherwise valid production qualification.
The aggregate collector deliberately ignores this diagnostic file, even if an
artifact claims it authorizes reuse. The report has no tokens or environment
values, contains `authorizesReuse: false` and `authorizesPublication: false`, and
explicitly lists runtime requirements that its source projections **do not**
establish. A source projection hash is not a reusable ISO identity.

Run locally (the output file must not already exist):

```sh
python3 scripts/ci/qualification-dependencies.py --output /tmp/source-boundaries.json
python3 tests/ci/qualification-dependencies.py
```

This change does **not** alter `image_identity.py`, qualification receipt reuse,
predecessor ISO eligibility, publication ancestry, freshness/approval gates, or
main-advance handling. The existing workflow source hash changes as for any
reviewed workflow edit; there is no migration or relabeling of old evidence.
No reduced rebuild count or runtime saving is claimed in this stage.

## Reviewed construction path and unresolved closure

1. `install-cli.sh` verifies the locked BlueBuild container with the repository
   CLI public key and installs its executable.
2. `iso.sh` verifies the immutable signed OS image, validates profile/channel,
   allocates a unique installation tag, and rechecks its digest before/after
   generation. It invokes `generate-iso --run-driver docker --variant kinoite`.
3. `prepare-installer.sh` uses the pinned installer lock and copies the installer
   directory into a temporary build context. It validates/derives the certificate
   DER bytes, installs the fstab hook, and constructs the local CLI alias with
   `docker build --pull=false --network=none`.
4. Diagnostic modes can modify the effective installer Containerfile and Lorax
   wrapper. Their helpers and mode selection therefore belong to generation.
5. Nix VM tools depend on `lib/ci-tools.nix`, the root lock, package construction
   and platform policy. Setup actions, actual realized tools, Docker/host kernel
   and firmware must also be accounted for; source hashes alone do not prove
   the effective environment. The inventory retains unreviewed support inputs
   conservatively rather than promising an exhaustive evaluated Nix closure.
6. `prepare-vm-iso.sh` personalizes a **copy** of the pristine ISO for testing.
   Its acceptance responsibilities must not be confused with original ISO bytes.

Future eligibility work must bind authenticated native run/artifact origins,
image/profile, actual tools and generated configuration, immutable installer and
CLI inputs, generation arguments and mode, and original `installation.json`/ISO
checksums. Random installation tags and volume IDs mean identical inputs do not
promise byte-identical rebuilt ISOs. Legacy absence remains a normal cache miss;
malformed present evidence must reject, not silently downgrade.

Keep current VM acceptance, policy, final main/predecessor checks and their
freshness requirements even if pristine ISO bytes eventually become reusable
across a controller-only change. First use these reports and mutation tests to
review the boundary; only a separate, reviewed eligibility change may use it.

## Validation

Mutation coverage changes each reviewed source in turn and checks exactly its
candidate domain hashes. Tests also cover unknown nested helpers, renames,
required missing inputs, executable modes, symlink targets/content, deterministic
output, secret-independent output, exclusive writes, and diagnostic collection.
Most importantly, a controller mutation that leaves the candidate generation
projection unchanged **still invalidates the existing qualification and
predecessor reuse inputs**. The authoritative gates have not been weakened.
