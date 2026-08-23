"""Focused behavior tests for the pinned OSBuild squashfs stage."""

import importlib.util
import pathlib
import sys
import types
from importlib.machinery import SourceFileLoader


def load_stage():
    osbuild = types.ModuleType("osbuild")
    osbuild.api = types.SimpleNamespace(arguments=lambda: None)
    osbuild_util = types.ModuleType("osbuild.util")
    osbuild_util.parsing = types.SimpleNamespace(parse_location=lambda value, _args: value)
    sys.modules["osbuild"] = osbuild
    sys.modules["osbuild.api"] = osbuild.api
    sys.modules["osbuild.util"] = osbuild_util

    path = pathlib.Path("installer/osbuild-stages/org.osbuild.squashfs")
    sys.dont_write_bytecode = True
    loader = SourceFileLoader("finite_squashfs_stage", str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def command_for(module, compression):
    commands = []
    module.subprocess.run = lambda command, check: commands.append((command, check))
    module.main(
        {
            "inputs": {"tree": {"path": "/input"}},
            "tree": "/output",
            "options": {
                "filename": "LiveOS/squashfs.img",
                "compression": compression,
                "exclude_paths": ["var/cache/.*"],
            },
        }
    )
    assert len(commands) == 1
    command, check = commands[0]
    assert check is True
    return command


stage = load_stage()

zstd_default = command_for(stage, {"method": "zstd"})
assert zstd_default == [
    "mksquashfs",
    "/input",
    "/output/LiveOS/squashfs.img",
    "-comp",
    "zstd",
    "-Xcompression-level",
    "1",
    "-regex",
    "-e",
    "var/cache/.*",
]

zstd_explicit = command_for(
    stage, {"method": "zstd", "options": {"compression-level": "3"}}
)
assert zstd_explicit.count("-Xcompression-level") == 1
assert zstd_explicit[zstd_explicit.index("-Xcompression-level") + 1] == "3"

lz4 = command_for(stage, {"method": "lz4"})
assert "-Xcompression-level" not in lz4
