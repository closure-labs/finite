#!/usr/bin/env python3
"""Workstation-only reviewed Brew cleanup. The default is a read-only preview."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile

BREW = '/home/linuxbrew/.linuxbrew/bin/brew'
FORMULA = re.compile(r'[A-Za-z0-9][A-Za-z0-9@+_.-]*(?:/[A-Za-z0-9][A-Za-z0-9@+_.-]*){0,2}')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def capture(*args):
    result = subprocess.run([BREW, *args], capture_output=True, check=True, timeout=120,
                            env=dict(os.environ, HOMEBREW_NO_AUTO_UPDATE='1'))
    if len(result.stdout) > 32 * 1024**2:
        raise ValueError('Brew inventory exceeds bound')
    return result.stdout.decode()


def stock(directory):
    files, formulae, uncertain = {}, set(), False
    for path in sorted(directory.rglob('*.Brewfile')):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024**2:
            raise ValueError('Unsafe upstream Brewfile')
        files[str(path.relative_to(directory))] = digest(path)
        for line in path.read_text().splitlines():
            text = line.strip()
            if not text or text.startswith('#'):
                continue
            match = re.fullmatch(r'(brew|cask|tap)\s+[\'\"]([^\'\"]+)[\'\"](?:\s*,.*)?', text)
            if not match:
                # Dynamic Ruby, includes or a new directive cannot prove absence.
                uncertain = True
            elif match[1] in ('brew', 'cask'):
                formulae.add(match[2]); formulae.add(match[2].split('/')[-1])
    if 'cli.Brewfile' not in files:
        raise ValueError('Inherited CLI Brewfile is required')
    return files, formulae, uncertain


def inventory(policy, directory, installed, proof=None):
    files, upstream, uncertain = stock(directory)
    declared = {entry['formula'] for entry in policy['packages']}
    rows = []
    for formula in installed['formulae']:
        name = formula['name']
        full_name = formula.get('full_name', name)
        reasons = []
        if name in upstream or full_name in upstream: reasons.append('upstream-bundle')
        if uncertain: reasons.append('uncertain-upstream-provenance')
        if name not in declared and full_name not in declared: reasons.append('not-a-historical-Finite-declaration')
        versions = formula.get('installed', [])
        if not versions or any(type(v.get('installed_on_request')) is not bool for v in versions):
            reasons.append('unknown-install-intent')
        elif any(v['installed_on_request'] for v in versions): reasons.append('user-requested')
        dependents = [other['name'] for other in installed['formulae']
                      if other['name'] != name and name in (other.get('dependencies', []) + other.get('optional_dependencies', [])
                                                           + other.get('recommended_dependencies', []))]
        if dependents: reasons.append('required-dependency')
        # A copied declaration and current installation do not establish who
        # installed it. Require a retained before/after transaction receipt.
        confirmed = False
        if isinstance(proof, dict) and proof.get('schema') == 1 and proof.get('installer') == 'finite-brew-bootstrap':
            before = proof.get('before', {}).get('formulae', [])
            after = proof.get('after', {}).get('formulae', [])
            prior = [row for row in before if row.get('full_name', row.get('name')) == full_name]
            added = [row for row in after if row.get('full_name', row.get('name')) == full_name]
            confirmed = (not prior and len(added) == 1 and bool(versions)
                         and added[0].get('installed') == versions)
        if not confirmed: reasons.append('uncertain-Finite-install-provenance')
        rows.append({'formula': full_name, 'eligible': not reasons, 'protectedBecause': reasons,
                     'dependents': sorted(dependents)})
    return {'schema': 1, 'mode': 'preview', 'upstreamBrewfiles': files, 'formulae': rows,
            'removals': sorted(row['formula'] for row in rows if row['eligible'])}


def machine():
    return digest(Path('/etc/machine-id'))


def active_generation():
    state = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state')))
    generation = state / 'nix/profiles/home-manager'
    return str(generation.resolve(strict=True))


def backup(destination, configuration, inventory_bytes, preview, review):
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(destination, 0o700)
    (destination / 'brew-inventory.json').write_bytes(inventory_bytes)
    (destination / 'preview.json').write_text(json.dumps(preview, indent=2) + '\n')
    (destination / 'review.json').write_text(json.dumps(review, indent=2) + '\n')
    # Preserve the entire personal tree, including profile, modules and locks.
    # Symlinks are archived as links; unrelated home directories are not followed.
    with tarfile.open(destination / 'home-configuration.tar.gz', 'w:gz', dereference=False) as archive:
        archive.add(configuration, arcname='home-manager', recursive=True)
        config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config')))
        for name in ('zsh', 'starship.toml', 'fish', 'homebrew'):
            path = config / name
            if path.exists() or path.is_symlink(): archive.add(path, arcname='config/' + name, recursive=True)
    (destination / 'generation.txt').write_text(active_generation() + '\n')


def apply(review, preview, policy, directory, configuration, backup_directory, proof=None):
    if (set(review) != {'schema', 'machineSha256', 'upstreamBrewfiles', 'replacementGeneration', 'removals', 'ownershipProofSha256'}
            or type(review['schema']) is not int or review['schema'] != 1
            or review['ownershipProofSha256'] != preview.get('ownershipProofSha256')
            or review['machineSha256'] != machine() or review['upstreamBrewfiles'] != preview['upstreamBrewfiles']
            or not isinstance(review['replacementGeneration'], str)
            or not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/]+', review['replacementGeneration'])
            or active_generation() != review['replacementGeneration']
            or not isinstance(review['removals'], list)
            or len(review['removals']) != len(set(review['removals']))
            or any(not isinstance(name, str) or not FORMULA.fullmatch(name) for name in review['removals'])
            or not set(review['removals']) <= set(preview['removals'])):
        raise ValueError('Reviewed removals must match this workstation, upstream ownership and active replacement generation')
    # Back up even for a reviewed empty list: that is a valid completed cleanup.
    current_bytes = capture('info', '--json=v2', '--installed').encode()
    backup(backup_directory, configuration, current_bytes, preview, review)
    (backup_directory / "historical-policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    if proof is not None:
        (backup_directory / "install-proof.json").write_text(json.dumps(proof, indent=2) + "\n")
    removed = []
    for name in review['removals']:
        if active_generation() != review['replacementGeneration']:
            raise ValueError('Replacement generation changed; stop cleanup')
        fresh = inventory(policy, directory, json.loads(capture('info', '--json=v2', '--installed')), proof)
        if fresh['upstreamBrewfiles'] != review['upstreamBrewfiles'] or name not in fresh['removals']:
            raise ValueError('Ownership or dependency state changed; stop cleanup')
        # Ask Brew's own dependency resolver immediately before each removal.
        if capture('uses', '--installed', '--recursive', name).strip():
            raise ValueError('Formula is still required by an installed application')
        subprocess.run([BREW, 'uninstall', name], check=True, timeout=300,
                       env=dict(os.environ, HOMEBREW_NO_AUTO_UPDATE='1', HOMEBREW_NO_AUTOREMOVE='1'))
        removed.append(name)
        (backup_directory / 'removed.json').write_text(json.dumps(removed) + '\n')
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--historical-policy', type=Path, required=True,
                        help='Reviewed historical Finite policy; declaration alone is insufficient for removal')
    parser.add_argument('--upstream-bundles', type=Path, default=Path('/usr/share/ublue-os/homebrew'))
    parser.add_argument('--configuration', type=Path, default=Path.home() / '.config/home-manager')
    parser.add_argument('--reviewed-removals', type=Path)
    parser.add_argument('--finite-install-proof', type=Path, help='Retained Finite installer before/after inventories; absence protects all uncertain packages')
    parser.add_argument('--backup-directory', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    policy = json.loads(args.historical_policy.read_text())
    proof = None
    if args.finite_install_proof:
        proof = json.loads(args.finite_install_proof.read_text())
        if (proof.get('machineSha256') != machine()
                or proof.get('policySha256') != digest(args.historical_policy)):
            raise ValueError('Installation provenance does not match this machine and policy')
    preview = inventory(policy, args.upstream_bundles, json.loads(capture('info', '--json=v2', '--installed')), proof)
    preview['ownershipProofSha256'] = digest(args.finite_install_proof) if args.finite_install_proof else None
    preview['machineSha256'] = machine()
    if args.apply:
        if args.reviewed_removals is None or args.backup_directory is None:
            parser.error('--apply requires --reviewed-removals and --backup-directory')
        review = json.loads(args.reviewed_removals.read_text())
        preview['removed'] = apply(review, preview, policy, args.upstream_bundles,
                                   args.configuration, args.backup_directory, proof)
        preview['mode'] = 'applied'
    print(json.dumps(preview, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Workstation cleanup stopped: ' + str(error), file=sys.stderr)
        sys.exit(2)
