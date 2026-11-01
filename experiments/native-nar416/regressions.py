"""Small real-engine HTTP completion/hash tests in disposable local Nix stores."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

PAYLOAD = b'finite-controlled-complete-body-test\n' * 16
CASES = ('ordinary', 'complete', 'mixed-case', 'missing', 'shorter', 'longer',
         'invalid', 'empty', 'signed-plus', 'signed-minus', 'trailing', 'overflow',
         'direct416', 'truncated', 'bad-hash', 'complete-bad-hash')


class Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def do_GET(self):
        mode = self.path.lstrip('/')
        header = self.headers.get('Range')
        self.server.requests.append(header)
        ordinary = mode in ('ordinary', 'bad-hash')
        if ordinary:
            self.send_response(200)
            self.send_header('Content-Length', str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)
            return
        if header is None and mode != 'direct416':
            body = PAYLOAD[:-1] if mode == 'truncated' else PAYLOAD
            self.send_response(200)
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Transfer-Encoding', 'chunked')
            self.end_headers()
            self.wfile.write(b'%x\r\n%s\r\n' % (len(body), body))
            self.wfile.flush()
            self.close_connection = True  # Deliberately omit the terminal chunk.
            return
        values = {'missing': None, 'shorter': f'bytes */{len(PAYLOAD)-1}',
                  'longer': f'bytes */{len(PAYLOAD)+1}', 'invalid': 'bytes */invalid',
                  'empty': 'bytes */', 'signed-plus': f'bytes */+{len(PAYLOAD)}',
                  'signed-minus': f'bytes */-{len(PAYLOAD)}', 'trailing': f'bytes */{len(PAYLOAD)}x',
                  'overflow': 'bytes */9223372036854775808', 'mixed-case': f'bYtEs */{len(PAYLOAD)}'}
        self.send_response(416)
        value = values.get(mode, f'bytes */{len(PAYLOAD)}')
        if value is not None:
            self.send_header('Content-Range', value)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *_args):
        pass


def main():
    package, output = map(Path, sys.argv[1:])
    for name in ('nix', 'nix-prefetch-url', 'nix-hash'):
        assert (package/'bin'/name).exists()
    results = []
    with tempfile.TemporaryDirectory(prefix='native416-protocol-') as directory:
        tmp = Path(directory)
        payload = tmp/'payload'
        payload.write_bytes(PAYLOAD)
        expected_output = subprocess.check_output([str(package/'bin/nix-hash'), '--type', 'sha256',
                                                   '--flat', '--base32', str(payload)], text=True).strip()
        for name in ('config', 'home', 'xdg'): (tmp/name).mkdir()
        server = Server(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            for case in CASES:
                server.requests = []
                env = dict(os.environ, HOME=str(tmp/'home'), XDG_CONFIG_HOME=str(tmp/'xdg'),
                           NIX_CONF_DIR=str(tmp/'config'), NIX_USER_CONF_FILES='/dev/null',
                           NIX_REMOTE='local?root='+str(tmp/('store-'+case)),
                           NIX_CONFIG='substituters =\nrequire-sigs = true\n')
                wrong = case in ('bad-hash', 'complete-bad-hash')
                expected = 'b'*64 if wrong else hashlib.sha256(PAYLOAD).hexdigest()
                command = [str(package/'bin/nix-prefetch-url'), '--store', env['NIX_REMOTE'],
                           '--option', 'http2', 'false', '--option', 'filetransfer-retry-attempts', '5',
                           '--option', 'filetransfer-retry-delay', '1', '--option', 'filetransfer-retry-jitter', 'false',
                           f'http://127.0.0.1:{server.server_port}/{case}', expected]
                result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=5)
                row = {'case': case, 'exitCode': result.returncode, 'ranges': server.requests,
                       'hashMismatch': 'hash mismatch' in result.stderr.lower(),
                       'http416': 'HTTP error 416' in result.stderr}
                results.append(row)
                if case in ('ordinary', 'complete', 'mixed-case'):
                    assert result.returncode == 0 and result.stdout.startswith(expected_output+'\n'), row
                elif wrong:
                    assert result.returncode != 0 and row['hashMismatch'], row
                else:
                    assert result.returncode != 0 and row['http416'], row
                if case in ('ordinary', 'bad-hash', 'direct416'):
                    assert server.requests == [None], row
                else:
                    count = len(PAYLOAD)-1 if case == 'truncated' else len(PAYLOAD)
                    assert server.requests == [None, f'bytes={count}-'], row
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
    (output/'regressions.json').write_text(json.dumps({'schema': 1, 'cases': results,
        'payloadBytes': len(PAYLOAD), 'http2': False, 'systemStoreUsed': False,
        'expectedHashEnforced': True, 'signatureChecksDisabled': False}, indent=2)+'\n')
    print(f'{len(results)} native completion/hash cases passed.')


if __name__ == '__main__':
    main()
