default:
    @just --list

# Format all repository sources with the pinned Flake formatter.
format:
    nix fmt

# Run the complete hermetic validation graph.
check:
    nix run .#ci

# Run repository checks interactively with the pinned toolchain.
ci:
    just check

# Build a named profile into a local OCI image.
build profile tag:
    nix run .#image-build -- {{ profile }} {{ tag }}

# Export generated profile artifacts for external consumers.
export-artifacts destination="artifacts":
    nix run .#export-artifacts -- {{ destination }}
