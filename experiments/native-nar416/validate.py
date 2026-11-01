"""One-off native backport build/test; metadata only, no installation/publication."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time

ROOT = Path.cwd()
SOURCE = ROOT / 'native-nix'
FILES = ROOT / 'experiments/native-nar416'
OUT = ROOT / '.native-nar416'
REV = '240bbbcb10d3fc4bce957fafc1000b85ffb004d0'
CORE = 'src/libstore/filetransfer.cc'
PATCHES = {'core.patch': 'bc7911d28e6d760b0487a04d8a6be9be20af5c912254c16bda1e797610fd6148',
           'tests.patch': 'c715ca6a8f5cbfbab5578df150daf2c4efa550c46afffc706b8001bbe4f62e47'}
ORIGINAL = '306a27e63a3bfa8aff8d3f787c7d3d0f0df6a8110c56e909ff2c0e104f62a2f2'
PATCHED = '520eaa72dc470487a400a03b3d1ee39e8f7978ea2f124138191acfad2aa96d61'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=kwargs.pop('timeout', 30), **kwargs).strip()


def save(value):
    OUT.mkdir(exist_ok=True)
    (OUT / 'result.json').write_text(json.dumps(value, indent=2) + '\n')


def prepare():
    assert capture(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD']) == REV
    assert not capture(['git', '-C', str(SOURCE), 'status', '--porcelain'])
    assert digest(SOURCE / CORE) == ORIGINAL
    for name, expected in PATCHES.items():
        assert digest(FILES / name) == expected
    lock = digest(SOURCE / 'flake.lock')
    args = ['git', '-C', str(SOURCE), 'apply', *[str(FILES / name) for name in PATCHES]]
    subprocess.run(args[:4] + ['--check'] + args[4:], check=True)
    subprocess.run(args, check=True)
    assert digest(SOURCE / CORE) == PATCHED
    assert set(capture(['git', '-C', str(SOURCE), 'diff', '--name-only']).splitlines()) == {
        CORE, 'tests/filetransfer-retry-backoff/test_retry_backoff.py'}
    save({'schema': 1, 'stage': 'prepared', 'sourceRevision': REV, 'patches': PATCHES,
          'patchedSourceSha256': PATCHED, 'lockSha256': lock,
          'testSourceSha256': digest(SOURCE/'tests/filetransfer-retry-backoff/test_retry_backoff.py'),
          'experimentScripts': {name: digest(FILES/name) for name in ('validate.py', 'regressions.py')},
          'experimentRevision': os.environ['GITHUB_SHA'], 'run': os.environ['GITHUB_RUN_ID'],
          'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'runnerImage': os.environ.get('ImageVersion'),
          'cpuCount': os.cpu_count(), 'jobCapMinutes': 60, 'distributionChanged': False})


def build(record):
    start = time.monotonic()
    # No flake-provided cache/trust configuration, manual retry or install/profile link.
    result = capture(['nix', 'build', './native-nix#nix-cli', '--no-link', '--print-out-paths',
                      '--no-update-lock-file', '--no-write-lock-file', '--option', 'accept-flake-config', 'false',
                      '-L'], timeout=2900)
    paths = result.splitlines()
    assert len(paths) == 1 and re.fullmatch(r'/nix/store/[a-z0-9]{32}-[^/]+', paths[0])
    record.update(stage='built', binaryPackage=paths[0], buildSeconds=time.monotonic()-start)
    save(record)


def test(record):
    package = Path(record['binaryPackage'])
    binary = package / 'bin/nix'
    version = capture([str(binary), '--version'])
    assert 'Determinate Nix 3.24.1' in version and '2.35.3' in version
    links = capture(['ldd', str(binary)])
    matches = re.findall(r'libnixstore\.so\S* => (/nix/store/\S+)', links)
    assert len(matches) == 1
    library = Path(matches[0]).resolve(strict=True)
    library_root = Path(*library.parts[:4])
    deriver = capture(['nix-store', '--query', '--deriver', str(library_root)])
    assert deriver.startswith('/nix/store/') and deriver.endswith('.drv')
    drv = json.loads(capture(['nix', 'derivation', 'show', deriver]))
    assert len(drv) == 1
    env = next(iter(drv.values()))['env']
    attrs = json.loads(env.get('__json', '{}'))
    source = Path(env.get('src') or attrs['src'])
    candidates = [source / CORE, source / 'filetransfer.cc', source / 'libstore/filetransfer.cc']
    found = [path for path in candidates if path.is_file() and digest(path) == PATCHED]
    assert len(found) == 1, 'Loaded library does not bind the exact patched source'
    assert digest(SOURCE / CORE) == PATCHED and digest(SOURCE / 'flake.lock') == record['lockSha256']
    assert digest(SOURCE/'tests/filetransfer-retry-backoff/test_retry_backoff.py') == record['testSourceSha256']
    record.update(stage='binary-verified', version=version, binarySha256=digest(binary),
                  loadedLibstore=str(library), loadedLibstoreSha256=digest(library),
                  loadedLibstoreDeriver=deriver, compiledSource=str(found[0]),
                  curlLibraries=re.findall(r'libcurl\.so\S* => (/nix/store/\S+)', links))
    save(record)
    subprocess.run([sys.executable, str(FILES / 'regressions.py'), str(package), str(OUT)], check=True, timeout=90)
    with tempfile.TemporaryDirectory(prefix='native416-upstream-') as directory:
        tmp = Path(directory)
        for name in ('home', 'config', 'xdg'): (tmp / name).mkdir()
        child = dict(os.environ, HOME=str(tmp/'home'), XDG_CONFIG_HOME=str(tmp/'xdg'),
                     NIX_CONF_DIR=str(tmp/'config'), NIX_USER_CONF_FILES='/dev/null',
                     NIX_REMOTE='local?root='+str(tmp/'store'),
                     NIX_CONFIG='substituters =\nrequire-sigs = true\nfiletransfer-retry-jitter = false\n',
                     PATH=str(package/'bin')+':'+os.environ['PATH'])
        subprocess.run([sys.executable, str(SOURCE/'tests/filetransfer-retry-backoff/test_retry_backoff.py')],
                       env=child, check=True, timeout=120)
    record.update(stage='passed', upstreamAdaptedRegressions='pass', targetedRegressions='pass',
                  installed=False, binaryUploaded=False, productionKeysUsed=False)
    save(record)


if __name__ == '__main__':
    operation = sys.argv[1]
    try:
        if operation == 'prepare': prepare()
        else:
            record = json.loads((OUT/'result.json').read_text())
            {'build': build, 'test': test}[operation](record)
    except Exception as error:
        record = json.loads((OUT/'result.json').read_text()) if (OUT/'result.json').exists() else {'schema': 1}
        record.update(stage='failed', failedOperation=operation, exceptionClass=type(error).__name__)
        save(record)
        raise
