#!/usr/bin/env python3
"""Offline harness tests: no rclone binary, RPM or external process is executed."""
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('rclone_compat_test', ROOT / 'scripts/ci/rclone-compatibility.py')
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class Contracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_hosted_guard_rejects_workstation_before_execution(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(app.subprocess, 'Popen') as process:
            with self.assertRaises(app.ProbeError):
                app.collect(self.root / 'not-a-binary')
            process.assert_not_called()

    def test_reference_must_be_exact_hash_read_only_and_nonsymlink(self):
        binary = self.root / 'reference'
        binary.write_bytes(b'fixture, never executed')
        with patch.object(app.os, 'statvfs', return_value=Mock(f_flag=os.ST_RDONLY)):
            with self.assertRaisesRegex(app.ProbeError, 'hash differs'):
                app.authenticate(binary)
            with patch.object(app, 'EXPECTED_SHA256', hashlib.sha256(binary.read_bytes()).hexdigest()):
                fd = app.authenticate(binary)
                os.close(fd)
        with patch.object(app.os, 'statvfs', return_value=Mock(f_flag=0)):
            with self.assertRaisesRegex(app.ProbeError, 'read-only'):
                app.authenticate(binary)
        link = self.root / 'alias'
        link.symlink_to(binary)
        with self.assertRaisesRegex(app.ProbeError, 'nonsymlink'):
            app.authenticate(link)

    def test_fail_and_probe_error_are_distinct_from_pass(self):
        def raises(error):
            raise error
        for error, status in ((app.ContractFailure('leaked'), 'fail'),
                              (app.ProbeError('missing positive'), 'probe-error'),
                              (ConnectionRefusedError('unavailable'), 'probe-error'),
                              (subprocess.TimeoutExpired('fixture', 20), 'probe-error')):
            result = app.case_result('test', 'GHSA-fixture', lambda: raises(error))
            self.assertEqual(result['status'], status)
        self.assertEqual(app.case_result('test', None, lambda: {'positive': True})['status'], 'pass')

    def test_overall_deadline_cannot_be_swallowed_as_one_case_error(self):
        def expired():
            raise app.BudgetExpired()
        with self.assertRaises(app.BudgetExpired):
            app.case_result('test', None, expired)

    def test_process_has_clean_environment_limits_deadline_and_group_cleanup(self):
        runner = app.Runner(77, self.root)
        process = Mock(pid=99999, returncode=0)
        process.wait.side_effect = [subprocess.TimeoutExpired('fixture', 20), 0]
        with patch.object(app.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(app.os, 'killpg') as kill:
            with self.assertRaisesRegex(app.ProbeError, 'timed out'):
                runner.run(['version'])
        arguments, kwargs = spawn.call_args
        self.assertEqual(arguments[0][0], '/proc/self/fd/77')
        self.assertEqual(kwargs['pass_fds'], (77,))
        self.assertTrue(kwargs['start_new_session'])
        self.assertIs(kwargs['preexec_fn'], app.limits)
        self.assertNotIn('GITHUB_TOKEN', kwargs['env'])
        self.assertNotIn('AWS_ACCESS_KEY_ID', kwargs['env'])
        self.assertEqual(kwargs['env']['HOME'], str(self.root))
        kill.assert_called_once()
        process.wait.assert_any_call(timeout=20)

    def test_raw_http_preserves_traversal_target(self):
        connection = Mock()
        connection.getresponse.return_value = Mock(status=400, read=Mock(return_value=b'denied'))
        with patch.object(app.http.client, 'HTTPConnection', return_value=connection) as factory:
            self.assertEqual(app.request(1234, 'GET', '/test/../other_user/config'), (400, b'denied'))
        factory.assert_called_once_with('127.0.0.1', 1234, timeout=3)
        connection.request.assert_called_once_with('GET', '/test/../other_user/config', body=None, headers={})
        connection.close.assert_called_once()

    def local_runner(self, vulnerable=False, unrelated_failure=False):
        def run(args, success=True):
            if args[0] == 'copyto':
                Path(str(args[2]).removesuffix('.rclonelink')).symlink_to(Path(args[1]).read_text())
            elif args[0] == 'copy':
                source, destination = map(Path, args[1:3])
                hostile = list(source.rglob('authkeys'))
                if hostile:
                    if vulnerable:
                        target = destination / hostile[0].relative_to(source)
                        target.write_text('escaped')
                        return 0, b'', b''
                    return 1, b'', b'unknown option' if unrelated_failure else b'path escapes root via symlink'
                for path in source.rglob('file'):
                    (destination / path.relative_to(source)).write_bytes(path.read_bytes())
            return 0, b'', b''
        return Mock(run=Mock(side_effect=run))

    def test_links_contract_requires_negative_refusal_and_in_tree_positive(self):
        result = app.links(self.local_runner(), self.root)
        self.assertIn('in-tree-link-allowed', result['contracts'])

    def test_links_actual_outside_write_is_failure(self):
        with self.assertRaisesRegex(app.ContractFailure, 'escaped'):
            app.links(self.local_runner(vulnerable=True), self.root)

    def test_links_unrelated_cli_error_is_not_security_pass(self):
        with self.assertRaisesRegex(app.ProbeError, 'did not identify'):
            app.links(self.local_runner(unrelated_failure=True), self.root)

    def test_proxy_accepts_multiline_document_and_rejects_oversized_input(self):
        # Execute only our tiny generated Python fixture in-process, never rclone.
        import sys
        source = app.ftp_proxy_source({'attacker-token': '/fixture/attacker'})
        request = json.dumps({'user': 'shared', 'pass': 'attacker-token'}, indent=2).encode()
        output = io.StringIO()
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(request))), patch.object(sys, 'stdout', output):
            exec(compile(source, '<fixture-proxy>', 'exec'), {})
        self.assertEqual(json.loads(output.getvalue()), {'type': 'local', '_root': '/fixture/attacker'})
        with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(b'x' * 16385))), self.assertRaises(SystemExit):
            exec(compile(source, '<fixture-proxy>', 'exec'), {})

    def ftp_fixture(self, vulnerable=False, unavailable=False, denial='551 File not available', retrieval_unavailable=False):
        state = {'latest': None}
        @contextmanager
        def server(args, port):
            interval = args[args.index('--passive-port') + 1]
            low, high = map(int, interval.split('-'))
            self.assertGreater(high, low)  # goftp uses rand.Intn(high-low).
            self.assertLess(high - low, 16)
            self.assertIn('DEBUG', args)
            yield
        class FTP:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def connect(self, *args, **kwargs):
                if unavailable:
                    raise ConnectionRefusedError('fixture unavailable')
            def login(self, user, password):
                if password not in ('attacker-token', 'victim-token'):
                    raise app.ftplib.error_perm('530 denied')
                self.name = password.removesuffix('-token')
                state['latest'] = self.name
            def nlst(self):
                return [(state['latest'] if vulnerable else self.name) + '.txt']
            def retrbinary(self, command, callback):
                if command == 'RETR ' + self.name + '.txt' and not retrieval_unavailable:
                    callback((self.name + '-only\n').encode())
                    return
                raise app.ftplib.error_perm(denial)
        with patch.object(app, 'port_pair', return_value=(10001, 10002)), \
                patch.object(app.ftplib, 'FTP', FTP):
            return app.case_result('ftp', None, lambda: app.ftp_sessions(Mock(server=server), self.root))

    def test_ftp_two_identity_orders_and_denial_controls(self):
        self.assertEqual(self.ftp_fixture()['status'], 'pass')

    def test_ftp_conventional_file_denial_is_accepted(self):
        self.assertEqual(self.ftp_fixture(denial='550 File unavailable')['status'], 'pass')

    def test_ftp_unexpected_denial_is_probe_error(self):
        for denial in ('552 Storage exceeded', '530 Not authenticated', '5510 invalid'):
            with self.subTest(denial=denial):
                result = self.ftp_fixture(denial=denial)
                self.assertEqual(result['status'], 'probe-error')
                self.assertIn('not a file authorization refusal', result['reason'])
                shutil.rmtree(self.root / 'attacker')
                shutil.rmtree(self.root / 'victim')

    def test_ftp_unavailable_own_file_is_probe_error(self):
        self.assertEqual(self.ftp_fixture(retrieval_unavailable=True)['status'], 'probe-error')

    def test_ftp_rebinding_is_failure_and_connection_error_is_probe_error(self):
        self.assertEqual(self.ftp_fixture(vulnerable=True)['status'], 'fail')
        shutil.rmtree(self.root / 'attacker')
        shutil.rmtree(self.root / 'victim')
        result = self.ftp_fixture(unavailable=True)
        self.assertEqual(result['status'], 'probe-error')
        self.assertIn('FTP phase connect:attacker', result['reason'])

    def restic_fixture(self, private=False, vulnerable=False):
        observed, memory = [], {}
        @contextmanager
        def server(*args):
            yield
        def rc(port, operation, parameters):
            if operation == 'serve/start':
                self.assertTrue(parameters['fs'].startswith(':memory:'))
                return {'id': 'fixture-server'}
            if operation == 'operations/copyfile':
                if parameters['dstFs'].startswith(':memory:'):
                    memory[parameters['dstRemote']] = (self.root / parameters['srcRemote']).read_bytes()
                else:
                    (self.root / parameters['dstRemote']).write_bytes(memory[parameters['srcRemote']])
            return {}
        def request(port, method, path, body=None, headers=None):
            observed.append((method, path))
            if private and not headers:
                return 401, b''
            if '..' in path or '%2e' in path or '/./' in path:
                return (200, b'OUTSIDE-SECRET\n') if vulnerable else (400, b'bad request')
            if 'other_user' in path:
                return 403, b''
            return 200, b'INSIDE\n'
        with patch.object(app, 'port_pair', return_value=(10001, 10002)), \
                patch.object(app, 'rc', side_effect=rc), patch.object(app, 'request', side_effect=request):
            result = app.restic(Mock(server=server), self.root, private)
        self.assertTrue(any(method == 'DELETE' and '..' in path for method, path in observed))
        return result

    def test_restic_root_uses_memory_backend_and_literal_methods(self):
        self.assertIn('outside-sentinel-unchanged', self.restic_fixture()['contracts'])

    def test_restic_private_requires_cross_user_and_anonymous_denials(self):
        self.restic_fixture(private=True)

    def test_restic_traversal_leak_is_failure(self):
        with self.assertRaisesRegex(app.ContractFailure, 'traversal not rejected'):
            self.restic_fixture(vulnerable=True)

    def test_s3_proxy_protocol_rejects_unknown_and_password_credentials(self):
        import sys
        source = app.s3_proxy_source({'alice': ('/fixture/alice', 'alice-secret')})
        for request, allowed in (({'user': 'alice'}, True), ({'user': 'unknown'}, False),
                                 ({'user': 'alice', 'pass': ''}, False), ({'user': 'alice', 'public_key': ''}, False)):
            output = io.StringIO()
            with patch.object(sys, 'stdin', Mock(buffer=io.BytesIO(json.dumps(request, indent=2).encode()))), \
                    patch.object(sys, 'stdout', output):
                if allowed:
                    exec(compile(source, '<fixture-proxy>', 'exec'), {})
                    self.assertEqual(json.loads(output.getvalue()), {'type': 'local', '_root': '/fixture/alice',
                                                                     '_secret_access_key': 'alice-secret'})
                else:
                    with self.assertRaises(SystemExit):
                        exec(compile(source, '<fixture-proxy>', 'exec'), {})

    def test_sigv4_canonical_request_matches_independent_fixed_fixture(self):
        # Literal canonical request tests newline, host-port and payload binding.
        import hmac
        canonical = ('GET\n/bucket/alice.txt\n\nhost:127.0.0.1:1234\n'
                     'x-amz-content-sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855\n'
                     'x-amz-date:20261013T120000Z\n\nhost;x-amz-content-sha256;x-amz-date\n'
                     'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855')
        key = hmac.digest(b'AWS4alice-secret', b'20261013', 'sha256')
        key = hmac.digest(key, b'us-east-1', 'sha256')
        key = hmac.digest(key, b's3', 'sha256')
        key = hmac.digest(key, b'aws4_request', 'sha256')
        message = ('AWS4-HMAC-SHA256\n20261013T120000Z\n20261013/us-east-1/s3/aws4_request\n'
                   + hashlib.sha256(canonical.encode()).hexdigest()).encode()
        signature = hmac.digest(key, message, 'sha256').hex()
        headers = app.sigv4_headers('127.0.0.1:1234', 'GET', '/bucket/alice.txt', 'alice', 'alice-secret',
                                    timestamp='20261013T120000Z')
        self.assertTrue(headers['Authorization'].endswith('Signature=' + signature))
        changed = app.sigv4_headers('127.0.0.1:1234', 'GET', '/bucket/alice.txt', 'alice', 'alice-secret', b'changed',
                                    timestamp='20261013T120000Z')
        self.assertNotEqual(headers['Authorization'], changed['Authorization'])
        with self.assertRaises(app.ProbeError):
            app.sigv4_headers('localhost', 'GET', '/?unimplemented', 'alice', 'secret')

    def s3_fixture(self, vulnerable=False, broken=False, rebound=False, denial_status=403):
        servers = {}
        @contextmanager
        def manager(runner):
            def start(options):
                self.assertEqual(options['type'], 's3')
                port = len(servers) + 10000
                if 'auth_proxy' in options:
                    first = 'alice' if 'alice-proxy.py' in options['auth_proxy'] else 'carol'
                    self.assertEqual(options['fs'], str(self.root / 'trap'))
                    servers[port] = ('alice', 'bob') if first == 'alice' else ('carol',)
                else:
                    self.assertEqual(options['auth_key'], ['static,static-secret'])
                    servers[port] = ('static',)
                return port
            yield start
        def request(port, method, path, body, headers):
            auth = headers['Authorization']
            name = auth.split('Credential=', 1)[1].split('/', 1)[0]
            expected = app.sigv4_headers('127.0.0.1:' + str(port), method, path, name, name + '-secret', body,
                                         headers['X-Amz-Date'])
            valid = name in servers[port] and auth == expected['Authorization']
            if not valid:
                return (200, b'<ListAllMyBucketsResult/>') if vulnerable else (denial_status, b'<Error><Code>AccessDenied</Code></Error>')
            if broken:
                return 503, b'unavailable'
            target = self.root / name / path.lstrip('/')
            if method == 'PUT':
                target.write_bytes(body)
                return 200, b''
            if rebound and name == 'alice' and path.endswith('written.txt') and (self.root / 'bob/bucket/written.txt').exists():
                return 200, b'bob-write'
            return (200, target.read_bytes()) if target.exists() else (404, b'<Error><Code>NoSuchKey</Code></Error>')
        with patch.object(app, 'rc_servers', manager), patch.object(app, 'request', request):
            return app.case_result('s3', None, lambda: app.s3_authority(Mock(), self.root))

    def test_s3_positive_read_write_and_all_secret_denials(self):
        result = self.s3_fixture()
        self.assertEqual(result['status'], 'pass', result)
        self.assertGreater(len(result['evidence']['responses']), 25)

    def test_s3_accepting_wrong_secret_is_security_failure(self):
        self.assertEqual(self.s3_fixture(vulnerable=True)['status'], 'fail')

    def test_s3_broken_positive_is_probe_error(self):
        self.assertEqual(self.s3_fixture(broken=True)['status'], 'probe-error')

    def test_s3_rebound_identity_is_security_failure(self):
        self.assertEqual(self.s3_fixture(rebound=True)['status'], 'fail')

    def rc_ftp_fixture(self, accept_bad=False, leak=False):
        servers = {}
        @contextmanager
        def manager(runner):
            def start(options):
                self.assertEqual(options['fs'], str(self.root / 'trap'))
                self.assertEqual(options['type'], 'ftp')
                port = len(servers) + 10000
                servers[port] = 'alice' if 'alice-proxy.py' in options['auth_proxy'] else 'bob'
                return port
            yield start
        class FTP:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def connect(self, host, port, **kwargs): self.name = servers[port]
            def login(self, user, token):
                if not accept_bad and (user != 'shared' or token != self.name + '-token'):
                    raise app.ftplib.error_perm('530 denied')
            def nlst(self): return [self.name + '.txt']
            def retrbinary(self, command, callback):
                if command == 'RETR ' + self.name + '.txt':
                    callback((self.name + '-only').encode())
                else:
                    if leak:
                        callback(b'TRAP-SECRET')
                    raise app.ftplib.error_perm('551 File not available')
        with patch.object(app, 'rc_servers', manager), patch.object(app.ftplib, 'FTP', FTP):
            return app.case_result('rc-ftp', None, lambda: app.rc_ftp_proxies(Mock(), self.root))

    def test_rc_ftp_request_local_proxy_controls(self):
        result = self.rc_ftp_fixture()
        self.assertEqual(result['status'], 'pass', result)
        self.assertEqual(len(result['evidence']['responses']), 6)

    def test_rc_ftp_accepted_bad_credentials_are_failure(self):
        self.assertEqual(self.rc_ftp_fixture(accept_bad=True)['status'], 'fail')

    def test_rc_ftp_denial_with_leaked_bytes_is_failure(self):
        self.assertEqual(self.rc_ftp_fixture(leak=True)['status'], 'fail')

    def test_s3_unrelated_denial_is_probe_error(self):
        self.assertEqual(self.s3_fixture(denial_status=500)['status'], 'probe-error')

    def test_rc_cleanup_attempts_all_servers_and_requires_closed_ports(self):
        @contextmanager
        def server(*args): yield
        seen = []
        def rc(port, operation, options):
            seen.append((operation, options))
            return {'id': str(len(seen))}
        with patch.object(app, 'rc', rc), patch.object(app, 'free_port', side_effect=[10000, 10001, 10002]), \
                patch.object(app.socket, 'create_connection', side_effect=[Mock(), ConnectionRefusedError()]):
            with self.assertRaisesRegex(app.ProbeError, 'still accepts'):
                with app.rc_servers(Mock(server=server)) as start:
                    start({'type': 's3'})
                    start({'type': 'ftp'})
        self.assertEqual([x[0] for x in seen].count('serve/stop'), 2)

    def test_successful_subset_remains_incomplete_and_never_release_eligible(self):
        binary = self.root / 'fixture'
        binary.write_text('never executed')
        fd = os.open(binary, os.O_RDONLY)
        with patch.dict(os.environ, GITHUB_SHA='a' * 40), \
                patch.object(app, 'hosted_guard'), patch.object(app, 'authenticate', return_value=fd), \
                patch.object(app, 'smoke', return_value={}), patch.object(app, 'links', return_value={}), \
                patch.object(app, 'ftp_sessions', return_value={}), patch.object(app, 'restic', return_value={}), \
                patch.object(app, 'rc_ftp_proxies', return_value={}), patch.object(app, 's3_authority', return_value={}):
            report = app.collect(binary)
        self.assertEqual(report['status'], 'partial-pass')
        self.assertFalse(report['coverageComplete'])
        self.assertFalse(report['releaseEligible'])
        self.assertFalse(report['installationApproved'])
        self.assertEqual(report['dispositionsGranted'], [])
        self.assertTrue(all(gap['status'] == 'not-covered' for gap in report['gaps']))
        self.assertEqual(len(report['cases']), 7)


if __name__ == '__main__':
    unittest.main()
