"""Offline HTTP fixtures: never connect to a VPS or a purchased proxy."""
import contextlib
import copy
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('chain', ROOT / 'scripts/xui_chain_egress.py')
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


class WorkflowTest(unittest.TestCase):
    def exercise(self, generation, dry=False, drift=False, bad_upstream=False):
        original = {'outbounds': [{'tag': 'direct', 'protocol': 'freedom'},
                                  {'tag': 'blocked', 'protocol': 'blackhole'}], 'routing': {'rules': [
            {'type': 'field', 'ip': ['geoip:private'], 'outboundTag': 'blocked'},
            {'type': 'field', 'domain': ['domain:example.test'], 'outboundTag': 'direct'},
        ]}}
        inbound = {'id': 4, 'enable': True, 'protocol': 'vless', 'port': 443,
                   'settings': {'clients': []}, 'streamSettings': {
                       'network': 'tcp', 'security': 'reality', 'realitySettings': {
                           'serverNames': ['www.example.test'], 'shortIds': ['abcd'],
                           'settings': {'publicKey': 'fixture-public-key'}}}}
        state = {'template': copy.deepcopy(original), 'client': None, 'writes': [], 'reads': 0}

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def response(self, obj=None, status=200):
                data = json.dumps({'success': True, 'obj': obj}).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                path = self.path
                if path == '/csrf-token':
                    return self.response('fixture-csrf')
                if path == '/panel/api/inbounds/list':
                    ib = copy.deepcopy(inbound)
                    ib['settings'] = json.dumps({'clients': [state['client']] if state['client'] else []})
                    ib['streamSettings'] = json.dumps(ib['streamSettings'])
                    return self.response([ib])
                if generation == 'modern':
                    row = {'email': 'new-user', 'inboundIds': [4], 'client': state['client']}
                    if path == '/panel/api/clients/list':
                        return self.response([row] if state['client'] else [])
                    if path == '/panel/api/clients/get/new-user':
                        return self.response(row)
                    if path == '/panel/api/clients/links/new-user':
                        return self.response([M.legacy_vless_link(inbound, state['client'])])
                return self.response(status=404)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get('Content-Length', '0'))).decode()
                body = json.loads(raw) if self.headers.get('Content-Type') == 'application/json' else {
                    k: v[0] for k, v in parse_qs(raw).items()}
                path = self.path
                template_path = '/panel/xray/' if generation == 'legacy' else '/panel/api/xray/'
                if path == '/login':
                    return self.response()
                if path == template_path:
                    state['reads'] += 1
                    if drift and state['reads'] == 2:
                        state['template']['log'] = {'loglevel': 'warning'}
                    return self.response(json.dumps({'xraySetting': json.dumps(state['template']),
                                                     'outboundTestUrl': 'https://example.test/probe'}))
                if path == template_path + 'update':
                    state['writes'].append('template')
                    self.assert_test_url(body)
                    state['template'] = json.loads(body['xraySetting'])
                    return self.response()
                client_path = '/panel/api/inbounds/addClient' if generation == 'legacy' else '/panel/api/clients/add'
                if path == client_path:
                    state['writes'].append('client')
                    if generation == 'legacy':
                        state['client'] = json.loads(body['settings'])['clients'][0]
                    else:
                        state['client'] = dict(body['client'], id='00000000-0000-4000-8000-000000000001')
                    return self.response()
                if path == '/panel/api/server/restartXrayService':
                    state['writes'].append('restart')
                    return self.response()
                return self.response(status=404)

            def assert_test_url(self, body):
                if body['outboundTestUrl'] != 'https://example.test/probe':
                    raise AssertionError('existing test URL lost')

        def runtime(*_):
            cfg = copy.deepcopy(state['template'])
            cfg['inbounds'] = [copy.deepcopy(inbound)]
            cfg['inbounds'][0]['settings']['clients'] = [state['client']] if state['client'] else []
            return cfg

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as td, contextlib.ExitStack() as stack:
                root = Path(td)
                panel = root / 'panel.env'
                panel.write_text('XUI_BASE_URL=http://127.0.0.1:%s\nXUI_USER=fixture-user\nXUI_PASS=fixture-password\nXUI_SSH_ALIAS=fixture-node\n' % server.server_port)
                proxy = root / 'proxy.env'
                proxy.write_text('IPNEW_HOST=proxy.example.test\nIPNEW_PORT=1080\nIPNEW_USER=fixture-user\nIPNEW_PASS=fixture-password\n')
                output = root / 'delivery.json'
                args = M.build_parser().parse_args([
                    'chain-upsert', '--xui-env', str(panel), '--proxy-env', str(proxy), '--proxy-prefix', 'IPNEW',
                    '--inbound-id', '4', '--client-email', 'new-user', '--outbound-tag', 'new-exit',
                    '--public-host', 'node.example.test', '--expected-exit-ip', '203.0.113.20',
                    '--restart-wait', '0', '--output', str(output)] + (['--dry-run'] if dry else []))
                stack.enter_context(mock.patch.object(M, 'read_runtime', side_effect=runtime))
                stack.enter_context(mock.patch.object(M.shutil, 'which', return_value='/fixture/bin'))
                backup = stack.enter_context(mock.patch.object(M, 'backup_database', return_value='/fixture/backup'))
                upstream = stack.enter_context(mock.patch.object(M, 'verify_upstream', side_effect=M.OpsError('fixture failure') if bad_upstream else None))
                exit_test = stack.enter_context(mock.patch.object(M, 'verify_exit', return_value='203.0.113.20'))
                buffer = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                if drift or bad_upstream:
                    with self.assertRaises(M.OpsError):
                        M.command_chain_upsert(args)
                    self.assertEqual([], state['writes'])
                    exit_test.assert_not_called()
                else:
                    self.assertEqual(0, M.command_chain_upsert(args))
                    if dry:
                        self.assertEqual([], state['writes'])
                        backup.assert_not_called()
                        upstream.assert_not_called()
                    else:
                        self.assertEqual(['template', 'client', 'restart'], state['writes'])
                        delivery = json.loads(output.read_text())
                        self.assertTrue(delivery['verified'])
                        self.assertTrue(delivery['runtime_verified'])
                        self.assertEqual(generation, delivery['api_generation'])
                        self.assertEqual(0o600, output.stat().st_mode & 0o777)
                        self.assertTrue(Path(str(output) + '.vless.txt').read_text().startswith('vless://'))
                        self.assertEqual(original['routing']['rules'][0], state['template']['routing']['rules'][0])
                self.assertNotIn('fixture-password', buffer.getvalue())
                self.assertNotIn('vless://', buffer.getvalue())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)

    def test_both_api_generations(self):
        for generation in ('modern', 'legacy'):
            with self.subTest(generation=generation):
                self.exercise(generation)

    def test_dry_run_never_writes(self):
        for generation in ('modern', 'legacy'):
            with self.subTest(generation=generation):
                self.exercise(generation, dry=True)

    def test_concurrent_template_change_stops_before_write(self):
        self.exercise('legacy', drift=True)

    def test_failed_upstream_stops_before_write(self):
        self.exercise('legacy', bad_upstream=True)


if __name__ == '__main__':
    unittest.main()
