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
           'tests.patch': '656784033b008b786221abbcf35f67de0bfaf9616a0ecf08da0d8ebe315edcf1'}
ORIGINAL = '92865d00ce339532f7e15ed952479e1985500e02446c1497dd0523699aa0753d'
PATCHED = '0f7106c425f195a69f31a602670231b14fc0fa2c0b31bc89506004764e276432'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(args, **kwargs):
    return subprocess.check_output(args, text=True, timeout=kwargs.pop('timeout', 30), **kwargs).strip()


def save(value):
    OUT.mkdir(exist_ok=True)
    (OUT / 'result.json').write_text(json.dumps(value, indent=2) + '\n')


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate derivation metadata key')
        value[key] = item
    return value


def derivation_source(raw, deriver):
    """Accept pinned v4 and legacy JSON, retaining exact deriver/source binding."""
    value = json.loads(raw, object_pairs_hook=unique_object)
    assert isinstance(value, dict)
    if 'version' in value or 'derivations' in value:
        assert set(value) == {'version', 'derivations'}
        assert type(value['version']) is int and value['version'] == 4
        drvs, key = value['derivations'], Path(deriver).name
    else:
        drvs, key = value, deriver
    assert isinstance(drvs, dict) and set(drvs) == {key}
    drv = drvs[key]
    assert isinstance(drv, dict) and isinstance(drv.get('env'), dict)
    env = drv['env']
    sources = [env['src']] if 'src' in env else []
    if 'structuredAttrs' in drv:
        attrs = drv['structuredAttrs']
        assert isinstance(attrs, dict)
        if 'src' in attrs:
            sources.append(attrs['src'])
    if '__json' in env:
        attrs = json.loads(env['__json'], object_pairs_hook=unique_object)
        assert isinstance(attrs, dict)
        if 'src' in attrs:
            sources.append(attrs['src'])
    assert sources and all(isinstance(src, str) and re.fullmatch(
        r'/nix/store/[a-z0-9]{32}-[^/]+', src) for src in sources)
    assert len(set(sources)) == 1, 'Ambiguous derivation source'
    return Path(sources[0])


def prepare():
    assert capture(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD']) == REV
    assert not capture(['git', '-C', str(SOURCE), 'status', '--porcelain'])
    assert capture(['git', 'hash-object', str(SOURCE / CORE)]) == 'a25ee6218aaf876491b2404530a697534a3a2164'
    assert capture(['git', 'hash-object', str(SOURCE/'tests/filetransfer-retry-backoff/test_retry_backoff.py')]) == 'ce8140d908b37b1b0965f652063132d3882b3e62'
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
          'experimentScripts': {name: digest(FILES/name) for name in ('validate.py', 'regressions.py', 'test_validation.py')},
          'experimentRevision': os.environ['GITHUB_SHA'], 'run': os.environ['GITHUB_RUN_ID'],
          'attempt': os.environ['GITHUB_RUN_ATTEMPT'], 'runnerImage': os.environ.get('ImageVersion'),
          'cpuCount': os.cpu_count(), 'jobCapMinutes': 59, 'distributionChanged': False})


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
    source = derivation_source(capture(['nix', 'derivation', 'show', deriver]), deriver)
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
