# CI and testing objectives

Purplefin keeps fast source checks, image integration tests, publishing, and
end-to-end installer tests as separate layers. Trigger selection keeps feedback
focused while each failure identifies the contract that broke.

| Layer | Trigger | Objective |
| --- | --- | --- |
| Repository checks | Every pull request, merge candidate, and main build | Evaluate the pinned Nix flake, verify generated files, run shell and policy tests, and lint workflows. |
| Candidate image builds | Pull requests with affected profiles | Build changed profiles from verified immutable parents in validation mode. |
| Merge candidate builds | Native `merge_group` events with affected profiles | Build the changed profile graph from the temporary merge commit in validation mode. |
| Published image graph | Main pushes, daily schedule, or an explicit main dispatch | Publish only changed images, or every image when explicitly forced, with signatures, SPDX SBOMs, and provenance. |
| Installer end-to-end | Installer-affecting pull requests and merge candidates, weekly schedule, and Image Builder digest updates | Verify the payload signature, provenance, and SPDX attestation; reuse trusted installer layers; build and boot the generic Anaconda ISO; and attest its component manifest and files. |
| Release verification | Manual release dispatch | Reuse a complete published candidate, verify every profile signature, provenance, SPDX attestation, and source commit, and promote immutable digests. |

All third-party actions and artifact-building containers are commit- or
digest-pinned. Mutable tags discover available updates, and immutable digests
construct Purplefin artifacts. Generated files are checked against the Nix
model and updated through the explicit generation command.

Expensive tests stay scheduled or change-driven. Installer-affecting changes
select the reusable ISO build and fold its result into the stable `CI gate`;
other changes skip it. Trusted main runs update the shared registry cache while
candidate runs consume it with read-only package permissions. Package deletion
uses an environment-protected manual workflow. The stable `CI gate`, main-only
publication boundary, installer smoke boot, SBOM generation, signing,
attestation verification, and artifact manifests define the durable CI
contracts.
