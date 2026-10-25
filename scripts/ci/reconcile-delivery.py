#!/usr/bin/env python3
"""Reconcile preparation separately from read-only publisher monitoring."""
import importlib.util
import argparse
import os
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Reuse the read-only snapshot from this exact native job')
    args = parser.parse_args(argv)
    return reconcile(args.report)


def reconcile(report_path=None, delivery=None):
    if (os.environ.get('GITHUB_ACTIONS') != 'true' or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Delivery reconciliation requires trusted hosted main')
    if delivery is None:
        spec = importlib.util.spec_from_file_location('delivery_health', Path(__file__).with_name('delivery-health.py'))
        delivery = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(delivery)
    revision = os.environ['GITHUB_SHA']
    report = (delivery.read_snapshot(report_path) if report_path else
              delivery.inspect(revision, delivery.root_version(), os.environ.get('FINITE_REVIEW_BOT_LOGIN')))
    result = delivery.dispatch(report, revision)
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
        output.write('\nPreparation reconciliation: ' + result + '\n')


if __name__ == '__main__':
    main()
