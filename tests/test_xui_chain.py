#!/usr/bin/env python3
import importlib.util
import json
import os
import tempfile
import unittest
import urllib.error
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "xui_chain_egress.py"
SPEC = importlib.util.spec_from_file_location("xui_chain_egress", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TemplateMergeTest(unittest.TestCase):
    def test_user_route_precedes_domains_but_preserves_security_prefix(self):
        rules = [
            {"type": "field", "inboundTag": ["api"], "outboundTag": "api"},
            {"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"},
            {"type": "field", "user": ["existing"], "outboundTag": "fixed-exit"},
            {"type": "field", "domain": ["domain:example.test"], "outboundTag": "fixed-exit"},
            {"type": "field", "network": "tcp,udp", "outboundTag": "direct"},
        ]
        template = {"outbounds": [{"tag": "direct", "protocol": "freedom"}],
                    "routing": {"rules": rules}}
        proxy = dict(protocol="socks5", host="proxy.example.test", port=1080,
                     username="fixture-user", password="fixture-password")
        result = MODULE.merge_chain_egress(template, proxy, "new-user", "new-exit")
        updated = result["routing"]["rules"]
        self.assertEqual(rules[:2], updated[:2])
        self.assertEqual(["new-user"], updated[2]["user"])
        self.assertEqual(rules, [r for r in updated if r.get("user") != ["new-user"]])
        self.assertEqual(rules, template["routing"]["rules"])

    def test_shared_rule_and_reserved_default_are_rejected(self):
        proxy = dict(protocol="socks5", host="proxy.example.test", port=1080,
                     username="fixture-user", password="fixture-password")
        for rule in [
            {"type": "field", "user": ["new-user", "other"], "outboundTag": "new-exit"},
            {"type": "field", "domain": ["domain:example.test"], "outboundTag": "new-exit"},
            {"type": "field", "user": ["new-user"], "outboundTag": "different-exit"},
        ]:
            with self.subTest(rule=rule), self.assertRaises(MODULE.OpsError):
                MODULE.merge_chain_egress({"routing": {"rules": [rule]}}, proxy, "new-user", "new-exit")
        with self.assertRaises(MODULE.OpsError):
            MODULE.merge_chain_egress({}, proxy, "new-user", "direct")

    def test_merge_is_idempotent_and_preserves_unrelated_config(self):
        template = {
            "outbounds": [
                {"tag": "direct", "protocol": "freedom", "settings": {}},
                {"tag": "egress-us", "protocol": "freedom", "settings": {}},
            ],
            "routing": {
                "domainStrategy": "AsIs",
                "rules": [
                    {"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"},
                    {"type": "field", "user": ["phone-us"], "outboundTag": "egress-us"},
                ],
            },
        }
        proxy = {
            "protocol": "socks5",
            "host": "proxy.example.test",
            "port": 1080,
            "username": "user",
            "password": "pass",
        }

        once = MODULE.merge_chain_egress(template, proxy, "phone-us", "egress-us")
        twice = MODULE.merge_chain_egress(once, proxy, "phone-us", "egress-us")

        self.assertEqual(once, twice)
        self.assertEqual("direct", twice["outbounds"][0]["tag"])
        self.assertEqual(1, sum(o.get("tag") == "egress-us" for o in twice["outbounds"]))
        self.assertEqual(1, sum(r.get("outboundTag") == "egress-us" for r in twice["routing"]["rules"]))
        self.assertEqual("geoip:private", twice["routing"]["rules"][0]["ip"][0])


class XuiApiContractTest(unittest.TestCase):
    def setUp(self):
        self.client = MODULE.XUIClient.__new__(MODULE.XUIClient)
        self.calls = []

        def post_form(path, data):
            self.calls.append(("form", path, data))
            return {"success": True}

        def post_json(path, data):
            self.calls.append(("json", path, data))
            return {"success": True}

        self.client.post_form = post_form
        self.client.post_json = post_json

    def test_template_update_uses_form_endpoint(self):
        self.client.update_xray_template({"outbounds": []}, "https://example.test/204")

        kind, path, body = self.calls[0]
        self.assertEqual("form", kind)
        self.assertEqual("/panel/api/xray/update", path)
        self.assertEqual({"outbounds": []}, json.loads(body["xraySetting"]))
        self.assertEqual("https://example.test/204", body["outboundTestUrl"])

    def test_client_create_and_force_restart_use_3x_ui_3x_paths(self):
        self.client.create_client("phone-us", 7)
        self.client.force_restart_xray()

        self.assertEqual("/panel/api/clients/add", self.calls[0][1])
        self.assertEqual([7], self.calls[0][2]["inboundIds"])
        self.assertEqual("/panel/api/server/restartXrayService", self.calls[1][1])

    def test_read_only_detection_falls_back_only_on_404(self):
        def post(path, data):
            self.calls.append(path)
            if path == "/panel/api/xray/":
                raise urllib.error.HTTPError("https://panel.example.test", 404, "not found", {}, None)
            return {"success": True, "obj": json.dumps({"xraySetting": "{}"})}
        self.client.post_form = post
        self.assertEqual("{}", self.client.xray_envelope()["xraySetting"])
        self.assertEqual("legacy", self.client.api_generation)
        self.client.update_xray_template({})
        self.assertEqual("/panel/xray/update", self.calls[-1])
        for code in (401, 403, 500):
            self.client.api_generation = "auto"
            with mock.patch.object(self.client, 'post_form', side_effect=urllib.error.HTTPError(
                    "https://panel.example.test", code, "error", {}, None)) as call:
                with self.assertRaises(urllib.error.HTTPError):
                    self.client.xray_envelope()
                self.assertEqual(1, call.call_count)

    def test_legacy_client_uses_add_client_api_not_database(self):
        self.client.api_generation = "legacy"
        self.client.create_client("new-user", 4)
        kind, path, data = self.calls[0]
        self.assertEqual(("form", "/panel/api/inbounds/addClient"), (kind, path))
        new = json.loads(data["settings"])["clients"][0]
        self.assertEqual("new-user", new["email"])
        self.assertTrue(new["id"])
        self.assertTrue(new["subId"])
        self.assertEqual(4, data["id"])


class LegacyLinkTest(unittest.TestCase):
    def test_export_uses_persisted_client_and_public_reality_settings(self):
        inbound = {
            "enable": True, "protocol": "vless", "port": 443,
            "streamSettings": json.dumps({"network": "tcp", "security": "reality", "realitySettings": {
                "serverNames": ["www.example.test"], "shortIds": ["abcd"],
                "privateKey": "never-export-this", "settings": {"publicKey": "public-key", "fingerprint": "chrome"}}}),
        }
        client = {"id": "00000000-0000-4000-8000-000000000001", "email": "new-user", "flow": "xtls-rprx-vision"}
        link = MODULE.legacy_vless_link(inbound, client)
        self.assertNotIn("never-export-this", link)
        self.assertIn("pbk=public-key", link)
        self.assertTrue(MODULE.vless_link_uses_loopback(link))
        inbound['streamSettings'] = json.dumps({"network": "ws", "security": "none"})
        with self.assertRaises(MODULE.OpsError):
            MODULE.legacy_vless_link(inbound, client)

    def test_legacy_clients_are_normalized_without_losing_identity(self):
        client = MODULE.XUIClient.__new__(MODULE.XUIClient)
        client.api_generation = "legacy"
        client.get = mock.Mock(return_value={"success": True, "obj": [
            {"id": 4, "settings": json.dumps({"clients": [{"id": "fixture-id", "email": "new-user", "enable": True}]})}
        ]})
        rows = client.list_clients()
        self.assertEqual([4], rows[0]['inboundIds'])
        self.assertEqual('fixture-id', client.get_client('new-user')['client']['id'])


class PreflightTest(unittest.TestCase):
    def test_expected_exit_and_ssh_are_required_before_writes(self):
        args = MODULE.build_parser().parse_args([
            'chain-upsert', '--xui-env', 'panel.env', '--proxy-env', 'proxy.env',
            '--proxy-prefix', 'IPNEW', '--inbound-id', '4', '--client-email', 'new-user',
            '--outbound-tag', 'new-exit', '--output', 'delivery.json'])
        with mock.patch.object(MODULE, 'load_env', return_value={}), mock.patch.object(MODULE, 'connected_client') as client:
            with self.assertRaises(MODULE.OpsError):
                MODULE.command_chain_upsert(args)
            args.expected_exit_ip = '203.0.113.20'
            with self.assertRaises(MODULE.OpsError):
                MODULE.command_chain_upsert(args)
            client.assert_not_called()

    def test_upstream_credentials_only_use_stdin(self):
        proxy = dict(protocol='socks5', host='proxy.example.test', port=1080,
                     username='fixture-user', password='fixture-sensitive-password')
        response = mock.Mock(returncode=0, stdout='{"ok":true}')
        with mock.patch.object(MODULE.subprocess, 'run', return_value=response) as run:
            MODULE.verify_upstream({'XUI_SSH_ALIAS': 'fixture-node', 'XUI_SUDO': '1'}, proxy, '203.0.113.20')
        args, kwargs = run.call_args
        self.assertNotIn(proxy['password'], ' '.join(args[0]))
        self.assertIn(proxy['password'], kwargs['input'])
        self.assertIn('sudo -n python3', args[0][-1])

    def test_runtime_checks_exact_route_and_unrelated_state(self):
        original = {'outbounds': [{'tag': 'direct', 'protocol': 'freedom'}],
                    'routing': {'rules': []}, 'inbounds': [{'settings': {'clients': []}}]}
        expected = MODULE.merge_chain_egress(original, dict(protocol='socks5', host='proxy.example.test',
                     port=1080, username='fixture', password='fixture'), 'new-user', 'new-exit')
        runtime = json.loads(json.dumps(expected))
        runtime['inbounds'][0]['settings']['clients'] = [{'id': 'fixture-id', 'email': 'new-user'}]
        with mock.patch.object(MODULE, 'read_runtime', return_value=runtime):
            self.assertTrue(MODULE.verify_runtime_via_ssh({'XUI_SSH_ALIAS':'fixture'}, 'new-user', 'new-exit', expected, original, 'fixture-id'))
            runtime['outbounds'][0]['protocol'] = 'blackhole'
            self.assertFalse(MODULE.verify_runtime_via_ssh({'XUI_SSH_ALIAS':'fixture'}, 'new-user', 'new-exit', expected, original, 'fixture-id'))

    def test_regression_manifest_probes_private_link(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root/'route.txt').write_text('vless://fixture@node.example.test:443?security=reality')
            manifest = root/'routes.json'
            manifest.write_text(json.dumps([{'name':'protected', 'link_file':'route.txt', 'expected_exit_ip':'198.51.100.20'}]))
            args = mock.Mock(regression_manifest=str(manifest), xray_bin='xray', curl_bin='curl')
            with mock.patch.object(MODULE, 'verify_exit', return_value='198.51.100.20') as verify:
                self.assertEqual(['protected'], MODULE.verify_regressions(args))
                verify.assert_called_once()


class SidecarTest(unittest.TestCase):
    def test_loopback_share_link_requires_public_host_rewrite(self):
        link = (
            "vless://00000000-0000-4000-8000-000000000001@localhost:443"
            "?security=reality&type=tcp#phone-us"
        )

        self.assertTrue(MODULE.vless_link_uses_loopback(link))
        rewritten = MODULE.rewrite_vless_host(link, "node.example.test")
        self.assertFalse(MODULE.vless_link_uses_loopback(rewritten))
        self.assertIn("@node.example.test:443", rewritten)

    def test_vless_reality_link_renders_local_socks_sidecar(self):
        link = (
            "vless://00000000-0000-4000-8000-000000000001@node.example.test:443"
            "?encryption=none&flow=xtls-rprx-vision&security=reality"
            "&sni=www.example.test&fp=chrome&pbk=public-key&sid=abcd&type=tcp"
            "#phone-us"
        )

        config = MODULE.sidecar_config_from_vless(link, 19123)

        self.assertEqual("127.0.0.1", config["inbounds"][0]["listen"])
        self.assertEqual(19123, config["inbounds"][0]["port"])
        self.assertEqual("00000000-0000-4000-8000-000000000001", config["outbounds"][0]["settings"]["vnext"][0]["users"][0]["id"])
        reality = config["outbounds"][0]["streamSettings"]["realitySettings"]
        self.assertEqual("public-key", reality["publicKey"])
        self.assertEqual("abcd", reality["shortId"])

    def test_sensitive_writer_uses_owner_only_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "delivery.json"
            MODULE.write_sensitive(path, {"links": ["vless://secret"]})

            self.assertEqual(0o600, path.stat().st_mode & 0o777)
            self.assertEqual({"links": ["vless://secret"]}, json.loads(path.read_text()))


if __name__ == "__main__":
    unittest.main()
