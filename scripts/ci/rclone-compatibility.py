#!/usr/bin/env python3
"""Bounded, partial compatibility contracts for one authenticated testing reference.

Only a hosted unprivileged network-none container may execute the pinned binary.
Results do not authorize package adoption, waive findings, or qualify an image.
"""
import argparse
from contextlib import contextmanager
import ftplib
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import resource
import shlex
import signal
import socket
import stat
import subprocess
import tempfile
import time

EXPECTED_SHA256 = '0343a46124ac5f3d64396bfb33102e6d734541979036f5d0d931358902cd686e'
MAX_BINARY = 256 * 1024 * 1024
MAX_LOG = 256 * 1024
GAPS = [
    {'id': 'sftp-powershell-quote', 'advisory': 'GHSA-2m8m-jhrm-w6j2', 'status': 'not-covered',
     'reason': 'Requires exact captured SFTP shell invocation and separate real Windows interoperability fixture.'},
    {'id': 'rc-per-server-proxy', 'advisory': 'GHSA-p569-5gjg-9cmj', 'status': 'not-covered',
     'reason': 'FTP direct-server session test does not exercise RC-started FTP/S3 request-local proxies.'},
    {'id': 's3-proxy-secret-and-authority', 'advisory': 'GHSA-xwwr-4h3p-r22c', 'status': 'not-covered',
     'reason': 'Per-identity SigV4 secret and cross-server authority fixture remains required.'},
    {'id': 'mount', 'status': 'not-covered', 'reason': 'This capability-free container does not qualify FUSE mounting.'},
]


class ProbeError(Exception):
    pass


class ContractFailure(Exception):
    pass


class BudgetExpired(Exception):
    pass


def require(condition, message):
    if not condition:
        raise ContractFailure(message)


def positive(condition, message):
    if not condition:
        raise ProbeError(message)


def hosted_guard():
    if (os.environ.get('GITHUB_ACTIONS') != 'true'
            or os.environ.get('GITHUB_REPOSITORY') != 'closure-labs/finite'
            or not re.fullmatch(r'[0-9a-f]{40}', os.environ.get('GITHUB_SHA', ''))):
        raise ProbeError('Require hosted canonical repository and exact source revision')
    if os.geteuid() == 0 or not any(Path(p).exists() for p in ('/.dockerenv', '/run/.containerenv')):
        raise ProbeError('Require an unprivileged disposable container')
    caps = re.search(r'^CapEff:\s*([0-9a-f]+)$', Path('/proc/self/status').read_text(), re.M)
    if not caps or int(caps[1], 16) or {name for _, name in socket.if_nameindex()} != {'lo'}:
        raise ProbeError('Require no effective capabilities and loopback-only networking')


def authenticate(binary):
    if (not binary.is_absolute() or '..' in binary.parts
            or any(p.is_symlink() for p in (binary, *binary.parents))):
        raise ProbeError('Require canonical nonsymlink binary path')
    fd = os.open(binary, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        positive(stat.S_ISREG(info.st_mode) and 0 < info.st_size <= MAX_BINARY,
                 'Require bounded regular reference executable')
        positive(bool(os.statvfs(binary).f_flag & os.ST_RDONLY), 'Reference must be mounted read-only')
        with os.fdopen(os.dup(fd), 'rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        positive(digest == EXPECTED_SHA256, 'Reference binary hash differs from authenticated Fedora candidate')
        os.lseek(fd, 0, os.SEEK_SET)
        return fd
    except BaseException:
        os.close(fd)
        raise


def limits():
    # Do not cap virtual address space: Go reserves a large virtual heap.
    resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_LOG, MAX_LOG))
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    os.umask(0o077)


class Runner:
    def __init__(self, fd, root):
        self.fd, self.root, self.commands = fd, root, []
        self.config = root / 'empty.conf'
        self.config.write_text('')
        self.env = {'PATH': '/usr/bin:/bin', 'HOME': str(root), 'TMPDIR': str(root),
                    'XDG_CONFIG_HOME': str(root / 'config'), 'XDG_CACHE_HOME': str(root / 'cache'),
                    'GOMAXPROCS': '2', 'LANG': 'C.UTF-8'}

    @contextmanager
    def process(self, args):
        command = ['/proc/self/fd/' + str(self.fd), '--config', str(self.config),
                   '--retries', '1', '--low-level-retries', '1', '--contimeout', '2s', '--timeout', '3s', *map(str, args)]
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            process = subprocess.Popen(command, cwd=self.root, env=self.env, pass_fds=(self.fd,),
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       start_new_session=True, preexec_fn=limits)
            try:
                yield process, stdout, stderr
            finally:
                # Kill the whole private session, including an auth-proxy child.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
                stdout.seek(0); stderr.seek(0)
                out, err = stdout.read(MAX_LOG + 1), stderr.read(MAX_LOG + 1)
                self.commands.append({'args': list(map(str, args)), 'returncode': process.returncode,
                                      'stdoutSha256': hashlib.sha256(out).hexdigest(),
                                      'stderrSha256': hashlib.sha256(err).hexdigest(),
                                      'stderrTail': err[-4096:].decode(errors='replace')})

    def run(self, args, success=True):
        with self.process(args) as (process, stdout, stderr):
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired as error:
                raise ProbeError('Reference command timed out') from error
            stdout.seek(0); stderr.seek(0)
            out, err = stdout.read(MAX_LOG + 1), stderr.read(MAX_LOG + 1)
            positive(code >= 0 and len(out) <= MAX_LOG and len(err) <= MAX_LOG,
                     'Reference process hit signal/resource/output bound')
            if success:
                positive(code == 0, 'Positive command failed: ' + err[-512:].decode(errors='replace'))
            return code, out, err

    @contextmanager
    def server(self, args, port):
        with self.process(args) as (process, _, __):
            deadline = time.monotonic() + 10
            while True:
                positive(process.poll() is None, 'Reference server exited during startup')
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.2):
                        break
                except OSError:
                    positive(time.monotonic() < deadline, 'Reference server did not become ready')
                    time.sleep(0.05)
            yield
            positive(process.poll() is None, 'Reference server exited during contract')


def free_port():
    with socket.socket() as stream:
        stream.bind(('127.0.0.1', 0))
        return stream.getsockname()[1]


def port_pair():
    first, second = free_port(), free_port()
    while first == second:
        second = free_port()
    return first, second


def smoke(runner, root):
    _, version, _ = runner.run(['version'])
    positive(b'rclone v1.75.2' in version, 'Unexpected reference version output')
    source, destination = root / 'source', root / 'destination'
    source.mkdir(); destination.mkdir()
    (source / 'normal.txt').write_bytes(b'ordinary copy\n')
    runner.run(['copy', source, destination])
    require((destination / 'normal.txt').read_bytes() == b'ordinary copy\n', 'Copy changed bytes')
    (destination / 'obsolete.txt').write_text('remove only within fixture')
    (source / 'normal.txt').write_text('updated sync\n')
    runner.run(['sync', source, destination])
    require(not (destination / 'obsolete.txt').exists(), 'Sync did not remove obsolete fixture')
    require((destination / 'normal.txt').read_text() == 'updated sync\n', 'Sync changed bytes')
    runner.run(['check', source, destination])
    return {'controls': ['version', 'copy', 'sync', 'check']}


def links(runner, root):
    outside, destination = root / 'outside', root / 'destination'
    outside.mkdir(); destination.mkdir()
    (outside / 'sentinel').write_bytes(b'outside stays unchanged\n')
    payload = root / 'target'
    payload.write_text(str(outside))
    runner.run(['copyto', payload, destination / 'pwn.rclonelink', '--links'])
    positive((destination / 'pwn').is_symlink() and os.readlink(destination / 'pwn') == str(outside),
             'Fixture did not reproduce the external link')
    (destination / 'evil').symlink_to('.')
    for index, relative in enumerate(('pwn/authkeys', 'evil/pwn/authkeys')):
        source = root / ('source-' + str(index))
        (source / relative).parent.mkdir(parents=True)
        (source / relative).write_text('must never escape\n')
        # Keep destination Fs rooted at destination. copyto with pwn as the
        # destination root would test an explicitly selected different root.
        code, _, error = runner.run(['copy', source, destination, '--links'], success=False)
        require(not (outside / 'authkeys').exists(), 'Copy escaped destination through link')
        require(code != 0, 'External/nested link write was not refused')
        positive(re.search(rb'escap|outside|symlink', error, re.I), 'Refusal did not identify link confinement')
    (destination / 'sub').mkdir()
    (destination / 'link').symlink_to('sub')
    source = root / 'positive'
    (source / 'link').mkdir(parents=True)
    (source / 'link/file').write_bytes(b'in-tree allowed\n')
    runner.run(['copy', source, destination, '--links'])
    positive((destination / 'sub/file').read_bytes() == b'in-tree allowed\n', 'In-tree link positive failed')
    require(sorted(p.name for p in outside.iterdir()) == ['sentinel']
            and (outside / 'sentinel').read_bytes() == b'outside stays unchanged\n', 'Outside content changed')
    return {'contracts': ['external-link-refused', 'nested-link-refused', 'in-tree-link-allowed'],
            'remainingScope': 'Concurrent link races and directory metadata writes are not covered here.'}


def ftp_proxy_source(roots):
    # Pinned rclone proxy.run supplies json.MarshalIndent bytes via cmd.Stdin,
    # not a newline-framed record. Read one bounded complete JSON document.
    return ('import json,sys\n'
            'raw=sys.stdin.buffer.read(16385)\n'
            'if len(raw)>16384: sys.exit(1)\n'
            'request=json.loads(raw)\n'
            'roots=' + repr(roots) + '\n'
            'if request.get("user") != "shared" or request.get("pass") not in roots: sys.exit(1)\n'
            'print(json.dumps({"type":"local","_root":roots[request["pass"]]}))\n')


def ftp_sessions(runner, root):
    roots = {}
    for name in ('attacker', 'victim'):
        directory = root / name
        directory.mkdir()
        (directory / (name + '.txt')).write_text(name + '-only\n')
        roots[name + '-token'] = str(directory)
    proxy = root / 'proxy.py'
    proxy.write_text(ftp_proxy_source(roots))
    port, passive = port_pair()
    # goftp v2.0.3 computes min + rand.Intn(max-min): equal endpoints
    # are invalid. Give simultaneous sessions a small nonempty port range.
    while passive > 65526 or passive <= port < passive + 8:
        passive = free_port()
    args = ['--log-level', 'DEBUG', 'serve', 'ftp', '--addr', '127.0.0.1:' + str(port),
            '--passive-port', f'{passive}-{passive + 8}', '--auth-proxy', shlex.join(['/usr/bin/python3', str(proxy)])]
    phase = 'server-startup'
    try:
        with runner.server(args, port):
            for first, second in (('attacker', 'victim'), ('victim', 'attacker')):
                with ftplib.FTP() as left, ftplib.FTP() as right:
                    for client, name in ((left, first), (right, second)):
                        phase = 'connect:' + name
                        client.connect('127.0.0.1', port, timeout=3)
                        try:
                            phase = 'login:' + name
                            client.login('shared', name + '-token')
                            phase = 'initial-list:' + name
                            positive(client.nlst() == [name + '.txt'], 'FTP authenticated positive root mismatch')
                            phase = 'positive-retrieval:' + name
                            own_bytes = bytearray()
                            client.retrbinary('RETR ' + name + '.txt', own_bytes.extend)
                            positive(own_bytes == (name + '-only\n').encode(), 'FTP authenticated retrieval mismatch')
                        except ftplib.error_perm as error:
                            raise ProbeError('FTP positive login/listing failed') from error
                    phase = 'retained-session-list:' + first
                    require(left.nlst() == [first + '.txt'], 'Later login rebound earlier FTP session')
                    phase = 'cross-root-retrieval:' + first + '-to-' + second
                    received = bytearray()
                    try:
                        left.retrbinary('RETR ' + second + '.txt', received.extend)
                    except ftplib.error_perm as error:
                        # goftp v2.0.3 RETR maps GetFile errors to 551;
                        # 550 is the conventional file-unavailable refusal.
                        positive(str(error).split(' ', 1)[0] in ('550', '551'),
                                 'FTP denial was not a file authorization refusal')
                    else:
                        raise ContractFailure('Earlier FTP session retrieved another identity file')
                    require(not received, 'FTP cross-session response leaked bytes')
            with ftplib.FTP() as denied:
                phase = 'bad-token-connect'
                denied.connect('127.0.0.1', port, timeout=3)
                try:
                    phase = 'bad-token-login'
                    denied.login('shared', 'wrong-token')
                except ftplib.error_perm as error:
                    positive(str(error).startswith('530'), 'FTP login denial was not an authentication refusal')
                else:
                    raise ContractFailure('FTP accepted unknown proxy token')
    except (OSError, ftplib.Error) as error:
        raise ProbeError('FTP phase ' + phase + ': ' + type(error).__name__ + ': ' + str(error)) from error
    for name in ('attacker', 'victim'):
        require((root / name / (name + '.txt')).read_text() == name + '-only\n', 'FTP sentinel changed')
    return {'contracts': ['simultaneous-same-user-isolation-both-orders', 'cross-root-retrieval-denied', 'unknown-token-denied']}


def request(port, method, path, body=None, headers=None):
    # http.client preserves literal dot segments; urllib/request would hide the
    # exact hostile request target under test in some callers.
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        raw = response.read(MAX_LOG + 1)
        positive(len(raw) <= MAX_LOG, 'HTTP fixture response exceeded bound')
        return response.status, raw
    finally:
        connection.close()


def rc(port, operation, parameters):
    status, raw = request(port, 'POST', '/' + operation, json.dumps(parameters), {'Content-Type': 'application/json'})
    positive(status == 200, 'RC fixture operation failed: ' + operation + ': ' + raw[-256:].decode(errors='replace'))
    return json.loads(raw)


def restic(runner, root, private=False):
    control, port = port_pair()
    memory = ':memory:compat-' + ('private' if private else 'root')
    (root / 'secret').write_bytes(b'OUTSIDE-SECRET\n')
    (root / 'inside').write_bytes(b'INSIDE\n')
    with runner.server(['rcd', '--rc-addr', '127.0.0.1:' + str(control), '--rc-no-auth'], control):
        outside_path = 'other_user/config' if private else 'outside-secret.txt'
        inside_path = 'test/config' if private else 'served-root/inside.txt'
        for source, target in (('secret', outside_path), ('inside', inside_path)):
            rc(control, 'operations/copyfile', {'srcFs': str(root), 'srcRemote': source,
                                                'dstFs': memory, 'dstRemote': target})
        options = {'type': 'restic', 'fs': memory if private else memory + '/served-root',
                   'addr': '127.0.0.1:' + str(port)}
        headers = {}
        if private:
            import base64
            options.update(private_repos=True, user='test', **{'pass': 'fixture-only'})
            headers['Authorization'] = 'Basic ' + base64.b64encode(b'test:fixture-only').decode()
        server = rc(control, 'serve/start', options)
        positive(isinstance(server.get('id'), str), 'RC did not return a server ID')
        try:
            status, body = request(port, 'GET', '/test/config' if private else '/inside.txt', headers=headers)
            positive(status == 200 and body == b'INSIDE\n', 'Restic benign read did not prove fixture readiness')
            paths = (('/test/../other_user/config', '/test/%2e%2e/other_user/config') if private else
                     ('/../outside-secret.txt', '/%2e%2e/outside-secret.txt', '/a/../../outside-secret.txt', '/./inside.txt'))
            for path in paths:
                for method in ('GET', 'HEAD', 'POST', 'DELETE'):
                    status, body = request(port, method, path, body=b'ATTACK' if method == 'POST' else None, headers=headers)
                    require(status == 400 and b'OUTSIDE-SECRET' not in body, 'Restic traversal not rejected: ' + method + ' ' + path)
            if private:
                status, _ = request(port, 'GET', '/other_user/config', headers=headers)
                require(status == 403, 'Restic ordinary other-user path not denied')
                status, _ = request(port, 'GET', '/test/config')
                require(status == 401, 'Restic anonymous request not denied')
            rc(control, 'operations/copyfile', {'srcFs': memory, 'srcRemote': outside_path,
                                                'dstFs': str(root), 'dstRemote': 'observed-secret'})
            require((root / 'observed-secret').read_bytes() == b'OUTSIDE-SECRET\n', 'Restic outside sentinel changed')
        finally:
            rc(control, 'serve/stop', {'id': server['id']})
    return {'contracts': ['memory-backend-positive-read', 'literal-and-encoded-traversal-rejected', 'outside-sentinel-unchanged']}


def case_result(name, advisory, function):
    try:
        return {'id': name, 'advisory': advisory, 'status': 'pass', 'evidence': function()}
    except ContractFailure as error:
        return {'id': name, 'advisory': advisory, 'status': 'fail', 'reason': str(error)}
    except (ProbeError, OSError, ValueError, KeyError, subprocess.SubprocessError, ftplib.Error, http.client.HTTPException) as error:
        return {'id': name, 'advisory': advisory, 'status': 'probe-error', 'reason': str(error)}


def collect(binary):
    hosted_guard()
    fd = authenticate(binary)
    try:
        with tempfile.TemporaryDirectory(prefix='finite-rclone-compat-') as temporary:
            root = Path(temporary)
            runner = Runner(fd, root)
            cases = []
            definitions = [('ordinary-copy-sync', None, smoke),
                           ('links-root-confinement', 'GHSA-cf44-9pgv-m4xc', links),
                           ('ftp-session-authority', 'GHSA-c476-6w5q-jw77', ftp_sessions),
                           ('restic-root-traversal', 'GHSA-45pq-889g-fcgh', restic),
                           ('restic-private-repository', 'GHSA-fqj9-69pf-6pjg', lambda r, p: restic(r, p, True))]
            for name, advisory, function in definitions:
                directory = root / name
                directory.mkdir()
                cases.append(case_result(name, advisory, lambda: function(runner, directory)))
            return {'schema': 1, 'binarySha256': EXPECTED_SHA256, 'sourceRevision': os.environ['GITHUB_SHA'],
                    'referenceScope': 'testing-candidate',
                    'status': 'probe-error' if any(c['status'] == 'probe-error' for c in cases) else
                              'fail' if any(c['status'] == 'fail' for c in cases) else 'partial-pass',
                    'cases': cases, 'gaps': GAPS, 'coverageComplete': False, 'releaseEligible': False,
                    'installationApproved': False, 'candidateBindingUnproven': True, 'dispositionsGranted': [],
                    'commands': runner.commands}
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if (not args.output.is_absolute() or '..' in args.output.parts
            or any(p.is_symlink() for p in (args.output, *args.output.parents))):
        parser.error('Require canonical nonsymlink output path')
    def deadline(signum, frame):
        raise BudgetExpired('Overall compatibility budget exceeded')
    signal.signal(signal.SIGALRM, deadline)
    signal.alarm(240)
    try:
        try:
            result = collect(args.binary)
        except (ProbeError, BudgetExpired, OSError, ValueError) as error:
            result = {'schema': 1, 'status': 'probe-error', 'reason': str(error),
                      'coverageComplete': False, 'releaseEligible': False, 'cases': [], 'gaps': GAPS}
        encoded = json.dumps(result, indent=2) + '\n'
        positive(len(encoded.encode()) <= 1024 * 1024, 'Report exceeds evidence bound')
        with args.output.open('x') as output:
            output.write(encoded)
        return {'partial-pass': 0, 'fail': 1, 'probe-error': 2}[result['status']]
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    raise SystemExit(main())
