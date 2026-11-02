#!/usr/bin/env python3
"""Signed, isolated fixture cache; never modifies persistent cache trust."""
import argparse
import http.server
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading

CASES = ('signed', 'signed-complete', 'unsigned', 'wrong-key', 'bad-hash')


def command(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=30, **kwargs)


def checked(args, **kwargs):
    result = command(args, **kwargs)
    if result.returncode:
        raise RuntimeError('Native fixture preparation failed: '+Path(args[0]).name)
    return result.stdout.strip()


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        path = (self.server.root/self.path.lstrip('/')).resolve()
        if not path.is_relative_to(self.server.root) or not path.is_file():
            self.send_error(404); return
        content = path.read_bytes()
        is_nar = path.parent.name == 'nar'
        if is_nar:
            self.server.nar_length = len(content)
            self.server.ranges.append(self.headers.get('Range'))
            if self.server.case == 'bad-hash':
                content = content[:-1]+bytes([content[-1] ^ 1])
            if self.server.case == 'signed-complete':
                if self.headers.get('Range'):
                    self.send_response(416)
                    self.send_header('Content-Range', f'bytes */{len(content)}')
                    self.send_header('Content-Length', '0')
                    self.end_headers(); return
                self.send_response(200)
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Transfer-Encoding', 'chunked')
                self.end_headers()
                self.wfile.write(b'%x\r\n%s\r\n' % (len(content), content))
                self.wfile.flush(); self.close_connection = True; return
        self.send_response(200)
        self.send_header('Content-Length', str(len(content)))
        self.end_headers(); self.wfile.write(content)

    def log_message(self, *_args): pass


def validate(runtime, target):
    nix, store = str(runtime/'bin/nix'), str(runtime/'bin/nix-store')
    rows = []
    # Private fixture signing material remains in this disposable directory.
    with tempfile.TemporaryDirectory(prefix='finite-signed-nar-') as directory:
        root = Path(directory)
        source = 'local?root='+str(root/'source')
        cache = root/'cache'
        private, public = root/'private', root/'public'
        checked([store, '--generate-binary-cache-key', 'finite-test', str(private), str(public)])
        private.chmod(0o600)
        paths = {}
        for case in CASES:
            value = root/(case+'.txt'); value.write_text('Finite signed NAR fixture: '+root.name+':'+case+'\n')
            paths[case] = checked([store, '--store', source, '--add', str(value)])
        checked([nix, '--extra-experimental-features', 'nix-command', 'store', 'sign', '--store', source,
                 '--key-file', str(private), *paths.values()])
        checked([nix, '--extra-experimental-features', 'nix-command', 'copy', '--from', source,
                 '--to', 'file://'+str(cache)+'?compression=none', *paths.values()])
        for case, path in paths.items():
            info = cache/(Path(path).name.split('-')[0]+'.narinfo')
            lines = info.read_text().splitlines()
            assert any(line.startswith('Sig: finite-test:') for line in lines)
            # CA paths otherwise bypass signatures by design. Removing CA makes
            # these fixtures require signatures; the signed fingerprint binds
            # the same exact path, NAR hash, size and references.
            lines = [line for line in lines if not line.startswith('CA:')]
            if case == 'unsigned': lines = [line for line in lines if not line.startswith('Sig:')]
            if case == 'wrong-key': lines = [line.replace('Sig: finite-test:', 'Sig: unknown-fixture:') for line in lines]
            info.write_text('\n'.join(lines)+'\n')
        httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        httpd.daemon_threads = True; httpd.root = cache.resolve()
        thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
        try:
            for case, path in paths.items():
                httpd.case, httpd.ranges = case, []
                result = command([store, '--store', target, '--realise', path,
                    '--option', 'substituters', f'http://127.0.0.1:{httpd.server_port}',
                    '--option', 'trusted-public-keys', public.read_text().strip(),
                    '--option', 'require-sigs', 'true', '--option', 'http2', 'false',
                    '--option', 'filetransfer-retry-delay', '1',
                    '--option', 'filetransfer-retry-jitter', 'false'])
                good = case in ('signed', 'signed-complete')
                assert (result.returncode == 0) == good, 'Signed NAR fixture verdict: '+case
                if good:
                    physical = Path(path) if target == 'daemon' else Path(target.split('root=', 1)[1])/path.lstrip('/')
                    assert physical.read_bytes() == (root/(case+'.txt')).read_bytes()
                    assert len(httpd.ranges) == (2 if case == 'signed-complete' else 1)
                    if case == 'signed-complete': assert httpd.ranges[1] == f'bytes={httpd.nar_length}-'
                elif case in ('unsigned', 'wrong-key'):
                    assert not httpd.ranges, 'Untrusted NAR body was requested'
                    assert 'not signed by any of the keys' in result.stderr.lower(), 'Expected signature rejection'
                else:
                    assert httpd.ranges and 'hash' in result.stderr.lower(), 'Expected NAR/hash rejection'
                rows.append({'case': case, 'expectedAccepted': good, 'accepted': result.returncode == 0,
                             'narRequests': len(httpd.ranges)})
        finally:
            httpd.shutdown(); httpd.server_close(); thread.join()
    return {'schema': 1, 'status': 'pass', 'target': target, 'requireSignatures': True,
            'persistentTrustChanged': False, 'cases': rows}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--isolated-selftest', type=Path)
    args = parser.parse_args()
    target = 'daemon' if args.isolated_selftest is None else 'local?root='+str(args.isolated_selftest.resolve())
    assert os.geteuid() == 0 or args.isolated_selftest is not None
    print(json.dumps(validate(args.runtime, target)))
