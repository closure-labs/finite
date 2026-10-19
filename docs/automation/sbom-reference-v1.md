# Finite full SBOM reference, version 1

Predicate type:
`https://github.com/closure-labs/finite/blob/main/docs/automation/sbom-reference-v1.md`

This custom in-toto predicate binds a complete native SPDX document to an exact
Finite image. GitHub's inline SBOM action limits documents to 16 MiB; the native
documents exceed that limit. Their unchanged bytes are stored as OCI referrers,
and this small predicate is signed through GitHub artifact attestations. Package,
file, relationship and license records remain in the complete native document.
Vulnerability admission and build provenance are independently verified. A
fresh current-run build receives new build provenance. Resumed candidates,
including those from an earlier run of the same source revision, must already
have valid provenance for the original source revision and trusted hosted main
builder. Missing original provenance requires a fresh build; a refreshed SBOM
reference records evidence for the same immutable bytes.

The predicate has these fields:

| Field | Contract |
| --- | --- |
| `schema` | Integer `1` |
| `image` | Exact `ghcr.io/closure-labs/finite@sha256:<64 hex>` subject |
| `profile` | `finite` or `finite-dev`, authenticated against image configuration |
| `platformDigest` | The authenticated linux/amd64 platform manifest digest |
| `sbom` | `name: sbom.spdx.json`, `mediaType: application/spdx+json`, `spdxVersion: SPDX-2.2` or `SPDX-2.3`, lowercase SHA256 hex in `sha256`, and positive byte `size` |
| `artifact` | Immutable same-repository OCI manifest `reference`, its `sha256:`-prefixed `digest`, `mediaType: application/vnd.oci.image.manifest.v1+json`, and positive byte `size` |

The referenced OCI manifest has artifact type `application/spdx+json`. Its
`subject` identifies the exact image digest and raw manifest descriptor. Its
single layer identifies the complete original SPDX document by SHA256 and byte
size, media type `application/spdx+json`, and title `sbom.spdx.json`. The publisher
authenticates the original native inventory, fetches the published manifest and
blob back by immutable digest, and verifies their bytes before signing the
reference predicate. Generated reference metadata lives outside native evidence.

Verification requires both the signed statement and the referenced bytes:

1. Verify the GitHub attestation signature, expected repository, reusable signer
   workflow, hosted runner identity, exact image subject and this predicate type.
   For example, supply the immutable image reference to `gh attestation verify`
   with `--repo closure-labs/finite`, `--signer-workflow
   closure-labs/finite/.github/workflows/attest-image.yml`, this type through
   `--predicate-type`, and `--deny-self-hosted-runners`.
2. Require the signed predicate's image, expected profile and platform digest to
   match the independently inspected image. Validate the version and field types.
3. Fetch `artifact.reference` by digest. Verify its raw SHA256, byte size, subject,
   artifact type and single full-document layer against the signed predicate.
   Mutable tags and a registry referrer listing are discovery aids.
4. Fetch the SPDX blob by its layer digest. Verify its complete byte size and
   SHA256 against `sbom` before parsing and using the document. Apply native
   document size bounds and use the original bytes without rewriting them.

This is an external SBOM binding with a custom predicate type. Consumers expecting
an inline SPDX predicate need to resolve the authenticated reference explicitly.
Retain referenced manifests and full SPDX blobs for the image's supported life.

The transport uses standard [OCI attachment support](https://oras.land/docs/commands/oras_attach/)
and GitHub's [custom attestation predicates](https://github.com/actions/attest/tree/1e69f48acb82d1966a394da916b4c1698aa569d6#custom-predicates).
