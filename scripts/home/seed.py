"""Generate an inert schema-3 seed using the bundled Foundation's pure rules."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import hashlib


def csv(value):
    return value.split(",") if value else []


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    for name in ("foundation", "user", "output"):
        result.add_argument("--" + name, required=True)
    for name in ("roles", "packages", "capabilities"):
        result.add_argument("--" + name, default="", help="Comma-separated selections")
    for name in ("hardware", "system", "form-factor", "cpu", "gpus", "model"):
        result.add_argument("--" + name)
    for name in ("camera", "fingerprint"):
        result.add_argument("--" + name, action=argparse.BooleanOptionalAction, default=None)
    return result


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, **kwargs)


def normalize(args, validator, catalog_file):
    if not validator.is_file():
        raise ValueError("The selected schema-3 Foundation has no bundled profile generator")
    catalog = json.loads(catalog_file.read_text())
    descriptor = json.loads((validator.parent / "profile-capabilities.json").read_text())
    if not isinstance(catalog, dict) or not isinstance(descriptor, dict):
        raise ValueError("Invalid Foundation writer metadata")
    if (type(catalog.get("schema")) is not int or catalog["schema"] != 3
            or type(catalog.get("profileSchema")) is not int or catalog["profileSchema"] != 3
            or descriptor.get("writeSchema") != 3 or 3 not in descriptor.get("initializeSchemas", [])
            or 3 not in descriptor.get("normalizeSchemas", [])
            or catalog.get("profileCapabilities") != descriptor):
        raise ValueError("Catalog does not match the bundled schema-3 Foundation writer")
    profile = {"schema": 3, "foundation": args.foundation,
               "roles": csv(args.roles), "packages": csv(args.packages), "capabilities": csv(args.capabilities),
               "identity": {"username": args.user, "homeDirectory": "/var/home/" + args.user}}
    if args.hardware is not None:
        profile["hardware"] = args.hardware
    host = {field: getattr(args, field) for field in ("system", "cpu", "model", "camera", "fingerprint")
            if getattr(args, field) is not None}
    if args.form_factor is not None:
        host["formFactor"] = args.form_factor
    if args.gpus is not None:
        host["gpus"] = csv(args.gpus)
    with tempfile.TemporaryDirectory(prefix="finite-seed-profile-") as temporary:
        profile_file, host_file = (Path(temporary) / name for name in ("profile.json", "host.json"))
        profile_file.write_text(json.dumps(profile))
        host_file.write_text(json.dumps(host))
        result = run(["nix-instantiate", "--store", "dummy://", "--eval", "--strict", "--json", str(validator),
                      "--argstr", "profileFile", str(profile_file), "--argstr", "hostFile", str(host_file)],
                     stdout=subprocess.PIPE)
        canonical = json.loads(result.stdout)["profile"]
    foundations = catalog.get("foundations", {})
    selection = foundations.get(args.foundation, {}) if isinstance(foundations, dict) else {}
    choices = selection.get("hardware", []) if isinstance(selection, dict) else []
    if not isinstance(choices, list) or canonical["hardware"] not in choices:
        raise ValueError("Profile is incompatible with the selected Finite image catalog")
    for field in ("roles", "packages", "capabilities"):
        available = catalog.get(field, {})
        if not isinstance(available, dict) or any(name not in available for name in canonical[field]):
            raise ValueError("Profile selects " + field + " outside the Finite image catalog")
    return canonical


def yaml(value):
    return run(["yq", "-P"], input=json.dumps(value), stdout=subprocess.PIPE).stdout


def create(args, validator, catalog_file):
    output = Path(args.output)
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists: " + str(output))
    profile = normalize(args, validator, catalog_file)
    contents = yaml(profile)
    with tempfile.TemporaryDirectory(prefix="finite-seed-") as temporary:
        stage = Path(temporary)
        user_data = "#cloud-config\n" + yaml({"preserve_hostname": True, "ssh_pwauth": False,
            "write_files": [{"path": "/etc/finite/home-profiles/" + args.user + ".yaml",
                             "permissions": "0644", "content": contents}]})
        (stage / "user-data").write_text(user_data)
        digest = hashlib.sha256(user_data.encode()).hexdigest()[:16]
        (stage / "meta-data").write_text(yaml({"instance-id": "finite-" + digest, "local-hostname": "finite"}))
        (stage / "profile.yaml").write_text(contents)
        run(["xorriso", "-as", "mkisofs", "-quiet", "-V", "cidata", "-J", "-R", "-o", str(stage / "seed.iso"),
             str(stage / "user-data"), str(stage / "meta-data")])
        output.mkdir(mode=0o755, parents=True)
        created = output.stat(follow_symlinks=False)
        try:
            for name in ("user-data", "meta-data", "profile.yaml", "seed.iso"):
                shutil.copyfile(stage / name, output / name)
                (output / name).chmod(0o644)
        except BaseException:
            # Only remove the directory this invocation exclusively created.
            try:
                current = output.lstat()
            except FileNotFoundError:
                pass
            else:
                if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                    shutil.rmtree(output)
            raise
    print("Seed generated; cloud-init is disabled by default on Finite. This ISO is inert unless an administrator "
          "explicitly enables full provisioning. Prefer importing profile.yaml with finite-home-init --profile.", file=sys.stderr)


def main(validator, catalog_file, argv):
    args = parser().parse_args(argv)
    try:
        create(args, validator, catalog_file)
    except (ValueError, OSError, TypeError, KeyError, subprocess.CalledProcessError) as error:
        print("Finite seed: " + str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit("Run finite-cloud-init to generate a seed")
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3:]))
