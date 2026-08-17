default:
    @just --list

# Format all repository sources with the pinned Flake formatter.
format:
    nix fmt

# Run the complete hermetic validation graph.
check:
    nix flake check --print-build-logs

# Run repository checks interactively with the pinned toolchain.
ci:
    nix run .#ci

# Build a named profile into a local OCI image.
build profile tag:
    nix run .#image-build -- {{ profile }} {{ tag }}

# Export generated profile artifacts for external consumers.
export-artifacts destination="artifacts":
    nix run .#export-artifacts -- {{ destination }}
