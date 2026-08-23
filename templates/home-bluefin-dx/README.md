# Finite Bluefin DX Home Manager

Choose any combination of Finite roles and let the bootstrap discover the
current username and home directory:

```console
nix run .#home-profile -- --foundation bluefin-dx --hardware generic-x86_64 --roles developer,support --format yaml >profile.yaml
nix run .#home-bootstrap -- --profile profile.yaml
```
