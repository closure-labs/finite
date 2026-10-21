#!/usr/bin/env python3
"""Collect both authenticated qualified images and fresh scans for release review.

This prepares evidence only. It neither signs nor publishes nor grants approval.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from release_set import CHANNELS, payload_digest, prepare, sha256
from security_decisions import load_json, normalize_findings
from release_versions import prerelease, previous_stable, release_version
from release_readiness import published_stable_pair

ROOT = Path(__file__).resolve().parents[2]


def helper_module():
    spec = importlib.util.spec_from_file_location('release_evidence', ROOT / 'scripts/bluebuild/release-evidence.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def authenticate_build(run, revision):
    helper_module().validate_run(run, 'build.yml', revision)
    if run.get('event') not in ('push', 'schedule', 'workflow_dispatch'):
        raise ValueError('Build producer must be a trusted main event')
    if run.get('status') != 'completed':
        raise ValueError('Build producer has not completed')
    return revision



def product_assets(iso_path, split_threshold=1992294400, part_size=1900 * 1024 * 1024):
    """Freeze GitHub-sized product parts before computing the approval payload."""
    if iso_path.stat().st_size <= split_threshold:
        return {iso_path.name: sha256(iso_path)}
    assets = {}
    with iso_path.open('rb') as source:
        index = 0
        while True:
            first = source.read(min(1024 * 1024, part_size))
            if not first:
                break
            if index > 999:
                raise ValueError('Qualified ISO exceeds bounded part count')
            part = iso_path.with_name(iso_path.name + f'.part-{index:03d}')
            digest = hashlib.sha256()
            remaining = part_size
            with part.open('xb') as output:
                chunk = first
                while chunk:
                    output.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                    if remaining <= 0:
                        break
                    chunk = source.read(min(1024 * 1024, remaining))
            assets[part.name] = digest.hexdigest()
            index += 1
    return assets


def channel_payload(channel, directory, revision):
    provenance = load_json(directory / 'provenance.json')
    if provenance.get('revision') != revision or provenance.get('isoMatchesQualification') is not True:
        raise ValueError('Release set requires preserved qualified ISO and matching source')
    qualification = provenance['qualification']
    iso = qualification['qualifiedIso']
    if iso.get('name') != channel + '.iso':
        raise ValueError('Qualified ISO name does not match channel')
    iso_path = directory / iso['name']
    if iso_path.is_symlink() or sha256(iso_path) != iso['sha256']:
        raise ValueError('Qualified ISO changed after authenticated collection')
    image = provenance['image']
    if not re.fullmatch(r'ghcr\.io/closure-labs/finite@sha256:[0-9a-f]{64}', image):
        raise ValueError('Release image identity is invalid')
    # Product bytes and the build recipe are immutable. Scan reports, provenance,
    # signatures and checksums are derived evidence and can be refreshed.
    assets = product_assets(iso_path)
    if iso_path.name not in assets:
        # The pristine full digest was checked above; persist only upload parts.
        iso_path.unlink()
    for path in directory.glob('*.Containerfile'):
        if path.is_symlink() or not path.is_file():
            raise ValueError('Build recipe must be a regular file')
        assets[path.name] = sha256(path)
    receipt = {'status': 'qualified', 'sourceRevision': revision,
               'imageDigest': image.split('@')[1], 'isoSha256': iso['sha256'],
               'producerBuildRun': provenance['buildRun'],
               'producerIsoRun': provenance['isoRun']}
    return {'imageDigest': receipt['imageDigest'], 'isoSha256': iso['sha256'], 'assets': assets}, receipt



def validate_scan_execution(scan, exit_code, profile, image):
    """Accept completed observations, never infer human clearance from scan status."""
    if not isinstance(scan, dict) or scan.get('image') != image or type(exit_code) is not int:
        raise ValueError('Release scan does not identify the requested image')
    status = scan.get('status')
    completed = (exit_code == 0 and (status == 'pass' or
                 (status == 'complete' and scan.get('scannerHealth') == 'healthy')))
    legacy_findings = exit_code == 1 and status == 'blocked'
    if not (completed or legacy_findings):
        raise ValueError('Release security scan failed technically')
    return normalize_findings(scan, profile)


def assemble(output, version, revision):
    payload = {'version': version, 'sourceRevision': revision, 'channels': {}}
    evidence = {}
    summary = ['# Paired prerelease review' if prerelease(version) else '# Official release review',
               '', f'Version: {version}', f'Source: `{revision}`', '',
               'Both images passed existing qualification and have fresh scan evidence.',
               'This proposal authorizes one release bundle; vulnerability acceptance is checked separately.', '']
    all_findings = []
    for channel in CHANNELS:
        entry, receipt = channel_payload(channel, output / ('release-' + channel), revision)
        entry['tag'] = channel + '-' + version
        payload['channels'][channel], evidence[channel] = entry, receipt
        result = load_json(output / ('security-' + channel) / 'security-result.json')
        if result.get('image') != 'ghcr.io/closure-labs/finite@' + entry['imageDigest']:
            raise ValueError('Scan identifies another image')
        findings = normalize_findings(result, channel)
        all_findings.extend(findings)
        receipt['scanResultSha256'] = sha256(output / ('security-' + channel) / 'security-result.json')
        receipt['scanStatus'] = result['status']
        summary.extend([f'## {channel}', '', f'Image: `{entry["imageDigest"]}`',
                        f'Qualified ISO SHA-256: `{entry["isoSha256"]}`',
                        f'Findings: {len(findings)}', ''])
        for finding in findings:
            advisory = finding['advisory']
            if advisory.startswith('CVE-'):
                link = 'https://www.cve.org/CVERecord?id=' + advisory
            elif advisory.startswith('GHSA-'):
                link = 'https://github.com/advisories/' + advisory
            else:
                link = None
            label = f'[{advisory}]({link})' if link else '`' + advisory + '`'
            summary.append(f'- {finding["severity"]}: {label}, `{finding["component"]}`, versions {", ".join(finding["versions"])}')
        summary.append('')
    document = prepare(payload, evidence)
    (output / 'release-set.json').write_text(json.dumps(document, sort_keys=True, indent=2) + '\n')
    proposal = {'schema': 1, 'kind': 'release-set', 'payload': payload}
    (output / 'release-set-proposal.json').write_text(json.dumps(proposal, sort_keys=True, indent=2) + '\n')
    (output / 'findings.json').write_text(json.dumps(all_findings, sort_keys=True, indent=2) + '\n')
    (output / 'summary.md').write_text('\n'.join(summary))
    return document


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-run', required=True)
    parser.add_argument('--output-directory', required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r'[1-9][0-9]{0,19}', args.build_run):
        raise ValueError('Invalid producer build run')
    if (os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or os.environ.get('GITHUB_REF') != 'refs/heads/main'):
        raise ValueError('Release preparation requires trusted repository main')
    revision = os.environ.get('GITHUB_SHA', '')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Missing trusted checkout revision')
    if Path.cwd().resolve() != ROOT:
        raise ValueError('Release preparation must run from the trusted checkout')
    # Reject unsupported versions before downloading either multi-gigabyte ISO.
    version = (ROOT / 'VERSION').read_text().strip()
    if not release_version(version):
        raise ValueError('Release preparation requires numeric MAJOR.MINOR.PATCH or MAJOR.MINOR.PATCH-dev VERSION')
    if prerelease(version) and not published_stable_pair(previous_stable(version)):
        raise ValueError('Development prerelease requires the preceding successful stable pair')
    helper = helper_module()
    run = helper.github('actions/runs/' + args.build_run)
    authenticate_build(run, revision)
    output = args.output_directory.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError('Release packet already exists')
    output.mkdir(parents=True)
    workspace = ROOT / '.bluebuild/release'
    if workspace.exists() or workspace.is_symlink():
        raise ValueError('Release evidence staging is not clean')
    for channel in CHANNELS:
        # Existing helper checks successful main producer, qualification, exact
        # archive digests, signatures, installer context and secure boot evidence.
        subprocess.run(['python3', str(ROOT / 'scripts/bluebuild/release-evidence.py'),
                        channel, '', args.build_run], check=True, timeout=3600)
        destination = output / ('release-' + channel)
        shutil.move(str(workspace), destination)
        provenance = load_json(destination / 'provenance.json')
        if provenance.get('isoMatchesQualification') is not True:
            raise ValueError('Both channels require preserved qualified ISO artifacts')
        result = subprocess.run(['bash', str(ROOT / 'scripts/bluebuild/security-run.sh'),
                                 provenance['image'], str(output / ('security-' + channel))],
                                check=False, timeout=3600)
        # A completed native scan with risk findings may await human review.
        # Scanner errors and incomplete coverage remain technical failures.
        scan = load_json(output / ('security-' + channel) / 'security-result.json')
        validate_scan_execution(scan, result.returncode, channel, provenance['image'])
    document = assemble(output, (ROOT / 'VERSION').read_text().strip(), revision)
    print(payload_digest(document))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write('payload_digest=' + payload_digest(document) + '\n')
            stream.write('packet_directory=' + str(output) + '\n')


if __name__ == '__main__':
    main()
