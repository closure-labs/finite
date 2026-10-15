#!/usr/bin/env python3
"""Expire pilot ISO archives beyond two successful generations per profile."""
import argparse
import importlib.util
from pathlib import Path
import sys
sys.dont_write_bytecode = True

spec = importlib.util.spec_from_file_location('qualified_iso_retention', Path(__file__).with_name('reuse-qualification.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
options_spec = importlib.util.spec_from_file_location('iso_retention_options', Path(__file__).resolve().parents[1] / 'ci/ci-options.py')
ci_options = importlib.util.module_from_spec(options_spec)
options_spec.loader.exec_module(ci_options)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true', help='Delete artifacts after trusted-main validation')
    args = parser.parse_args()
    for profile in ('bluefin-generic', 'bluefin-dx-generic'):
        if ci_options.iso_preservation_enabled(profile):
            module.prune_iso(profile, apply=args.apply)


if __name__ == '__main__':
    main()
