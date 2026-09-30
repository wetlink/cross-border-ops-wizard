#!/usr/bin/env python3
"""Persist a per-client proxy egress in legacy x-ui / 3x-ui and render sidecars.

Credentials are loaded from private env files. The tool never prints proxy
credentials or VLESS URLs; sensitive delivery material is written mode 0600.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import http.cookiejar
import json
import os
import re
import secrets
import shlex
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Iterator


DEFAULT_TEST_URL = "https://www.google.com/generate_204"
DEFAULT_RUNTIME_CONFIG = "/usr/local/x-ui/bin/config.json"
DEFAULT_DB_PATH = "/etc/x-ui/x-ui.db"


class OpsError(RuntimeError):
    pass


def load_env(path: str | Path) -> dict[str, str]:
    result: dict[str, str] = {}
    with Path(path).expanduser().open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def required(env: dict[str, str], *names: str) -> None:
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise OpsError("missing required env keys: " + ", ".join(missing))


def unwrap_json(value: Any) -> Any:
    while isinstance(value, str):
        value = json.loads(value)
    return value


def check_response(response: dict[str, Any], action: str) -> dict[str, Any]:
    if not response.get("success"):
        raise OpsError("%s failed (panel message withheld; inspect privately)" % action)
    return response


@contextlib.contextmanager
def ssh_tunnel(alias: str, remote_port: int) -> Iterator[int]:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    local_port = probe.getsockname()[1]
    probe.close()
    process = subprocess.Popen(
        [
            "ssh",
            "-o", "BatchMode=yes",
            "-o", "ExitOnForwardFailure=yes",
            "-N", "-L", "%d:127.0.0.1:%d" % (local_port, remote_port),
            alias,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            if process.poll() is not None:
                raise OpsError("SSH tunnel exited before becoming ready")
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.2)
        else:
            raise OpsError("SSH tunnel did not become ready")
        yield local_port
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


class XUIClient:
    def __init__(self, base_url: str, username: str, password: str, insecure: bool = False):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.csrf_token = ""
        self.api_generation = "auto"
        context = ssl._create_unverified_context() if insecure else ssl.create_default_context()
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies),
            urllib.request.HTTPSHandler(context=context),
        )

    def _request(self, method: str, path: str, body: bytes | None = None,
                 content_type: str | None = None) -> dict[str, Any]:
        request = urllib.request.Request(self.base_url + path, data=body, method=method)
        if content_type:
            request.add_header("Content-Type", content_type)
        if self.csrf_token:
            request.add_header("X-CSRF-Token", self.csrf_token)
        with self.opener.open(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def get(self, path: str) -> dict[str, Any]:
        return self._request("GET", path)

    def post_form(self, path: str, data: dict[str, Any]) -> dict[str, Any]:
        body = urllib.parse.urlencode(data).encode("utf-8")
        return self._request("POST", path, body, "application/x-www-form-urlencoded")

    def post_json(self, path: str, data: Any) -> dict[str, Any]:
        body = json.dumps(data, separators=(",", ":")).encode("utf-8")
        return self._request("POST", path, body, "application/json")

    def login(self) -> None:
        try:
            self.csrf_token = self.get("/csrf-token").get("obj", "")
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
        response = self.post_form("/login", {
            "username": self.username,
            "password": self.password,
        })
        check_response(response, "login")

    def list_clients(self) -> list[dict[str, Any]]:
        if getattr(self, "api_generation", "auto") == "legacy":
            rows = []
            for inbound in self.inbounds():
                for item in unwrap_json(inbound.get("settings", {})).get("clients", []):
                    rows.append({"email": item.get("email"), "inboundIds": [inbound["id"]], "client": item})
            return rows
        return check_response(self.get("/panel/api/clients/list"), "list clients").get("obj", [])

    def inbounds(self) -> list[dict[str, Any]]:
        return check_response(self.get("/panel/api/inbounds/list"), "list inbounds").get("obj", [])

    def get_client(self, email: str) -> dict[str, Any]:
        if getattr(self, "api_generation", "auto") == "legacy":
            rows = [row for row in self.list_clients() if row.get("email") == email]
            if len(rows) != 1:
                raise OpsError("legacy client absent or email ambiguous across inbounds")
            return rows[0]
        path = "/panel/api/clients/get/" + urllib.parse.quote(email, safe="")
        return check_response(self.get(path), "get client").get("obj", {})

    def create_client(self, email: str, inbound_id: int) -> dict[str, Any]:
        if getattr(self, "api_generation", "auto") == "legacy":
            item = {"id": str(uuid.uuid4()), "email": email, "enable": True,
                    "flow": "xtls-rprx-vision", "limitIp": 0, "totalGB": 0,
                    "expiryTime": 0, "tgId": "", "subId": secrets.token_hex(12), "reset": 0}
            return check_response(self.post_form("/panel/api/inbounds/addClient", {
                "id": inbound_id, "settings": json.dumps({"clients": [item]}),
            }), "create legacy client")
        return check_response(self.post_json("/panel/api/clients/add", {
            "client": {
                "email": email,
                "enable": True,
                "flow": "xtls-rprx-vision",
                "limitIp": 0,
                "totalGB": 0,
                "expiryTime": 0,
                "tgId": 0,
            },
            "inboundIds": [inbound_id],
        }), "create client")

    def attach_client(self, email: str, inbound_id: int) -> dict[str, Any]:
        if getattr(self, "api_generation", "auto") == "legacy":
            raise OpsError("legacy email belongs to another inbound; choose a new email")
        path = "/panel/api/clients/%s/attach" % urllib.parse.quote(email, safe="")
        return check_response(self.post_json(path, {"inboundIds": [inbound_id]}), "attach client")

    def xray_envelope(self) -> dict[str, Any]:
        generation = getattr(self, "api_generation", "auto")
        path = "/panel/xray/" if generation == "legacy" else "/panel/api/xray/"
        try:
            response = self.post_form(path, {})
            self.api_generation = "legacy" if generation == "legacy" else "modern"
        except urllib.error.HTTPError as error:
            if generation != "auto" or error.code != 404:
                raise
            response = self.post_form("/panel/xray/", {})
            self.api_generation = "legacy"
        check_response(response, "get Xray template")
        return unwrap_json(response.get("obj"))

    def update_xray_template(self, template: dict[str, Any], test_url: str = DEFAULT_TEST_URL) -> dict[str, Any]:
        path = "/panel/xray/update" if getattr(self, "api_generation", "auto") == "legacy" else "/panel/api/xray/update"
        return check_response(self.post_form(path, {
            "xraySetting": json.dumps(template, separators=(",", ":")),
            "outboundTestUrl": test_url or DEFAULT_TEST_URL,
        }), "update Xray template")

    def force_restart_xray(self) -> dict[str, Any]:
        return check_response(self.post_form("/panel/api/server/restartXrayService", {}), "force restart Xray")

    def client_links(self, email: str) -> list[str]:
        if getattr(self, "api_generation", "auto") == "legacy":
            row = self.get_client(email)
            inbound = next(b for b in self.inbounds() if b["id"] == row["inboundIds"][0])
            return [legacy_vless_link(inbound, row["client"])]
        path = "/panel/api/clients/links/" + urllib.parse.quote(email, safe="")
        return check_response(self.get(path), "get client links").get("obj", [])


def validate_inbound(inbound: dict[str, Any]) -> dict[str, Any]:
    stream = unwrap_json(inbound.get("streamSettings", {}))
    if (not inbound.get("enable") or inbound.get("protocol") != "vless"
            or stream.get("network") not in ("tcp", "raw") or stream.get("security") != "reality"):
        raise OpsError("chain-upsert supports enabled VLESS TCP/Reality inbounds only")
    return stream


def legacy_vless_link(inbound: dict[str, Any], client: dict[str, Any]) -> str:
    reality = validate_inbound(inbound)["realitySettings"]
    extra = reality.get("settings", {})
    names = reality.get("serverNames", [])
    sni = extra.get("serverName") or (names[0] if names else "")
    if not sni or not extra.get("publicKey") or not reality.get("shortIds") or not client.get("id"):
        raise OpsError("legacy inbound is missing public Reality parameters; do not regenerate keys")
    query = {"type": "tcp", "encryption": "none", "security": "reality",
             "flow": client.get("flow", ""), "sni": sni,
             "fp": extra.get("fingerprint") or "chrome", "pbk": extra["publicKey"],
             "sid": reality["shortIds"][0], "spx": extra.get("spiderX") or "/"}
    return "vless://%s@localhost:%d?%s#%s" % (
        urllib.parse.quote(client["id"], safe=""), inbound["port"], urllib.parse.urlencode(query),
        urllib.parse.quote(client["email"], safe=""))


def proxy_from_env(env: dict[str, str], prefix: str) -> dict[str, Any]:
    prefix = prefix.rstrip("_") + "_"
    keys = {name: prefix + name for name in ("HOST", "PORT", "USER", "PASS")}
    missing = [key for name, key in keys.items() if not env.get(key)]
    if missing:
        raise OpsError("missing proxy env keys: " + ", ".join(missing))
    protocol = env.get(prefix + "PROTOCOL", "socks5").lower()
    if protocol not in ("socks", "socks5", "http"):
        raise OpsError("unsupported proxy protocol: %s (expected socks5 or http)" % protocol)
    return {
        "protocol": protocol,
        "host": env[keys["HOST"]],
        "port": int(env[keys["PORT"]]),
        "username": env[keys["USER"]],
        "password": env[keys["PASS"]],
    }


def build_proxy_outbound(proxy: dict[str, Any], outbound_tag: str) -> dict[str, Any]:
    protocol = "socks" if proxy["protocol"] in ("socks", "socks5") else "http"
    return {
        "tag": outbound_tag,
        "protocol": protocol,
        "settings": {
            "servers": [{
                "address": proxy["host"],
                "port": int(proxy["port"]),
                "users": [{"user": proxy["username"], "pass": proxy["password"]}],
            }],
        },
    }


def merge_chain_egress(template: dict[str, Any], proxy: dict[str, Any],
                       client_email: str, outbound_tag: str) -> dict[str, Any]:
    if outbound_tag.lower() in ("direct", "blocked", "block", "reject", "api"):
        raise OpsError("reserved outbound tag; choose a dedicated tag")
    merged = copy.deepcopy(template)
    outbounds = merged.setdefault("outbounds", [])
    routing = merged.setdefault("routing", {})
    rules = routing.setdefault("rules", [])
    owned = {"type": "field", "user": [client_email], "outboundTag": outbound_tag}
    matches = [r for r in rules if r.get("outboundTag") == outbound_tag or client_email in (r.get("user") or [])]
    if any(r != owned for r in matches) or len(matches) > 1:
        raise OpsError("shared, constrained or conflicting route; refusing to change it")
    indices = [i for i, o in enumerate(outbounds) if o.get("tag") == outbound_tag]
    if len(indices) > 1 or (indices and (indices[0] == 0 or not matches)):
        raise OpsError("outbound ownership is not exclusive or is the default outbound")
    for outbound in outbounds:
        if (outbound.get("proxySettings", {}).get("tag") == outbound_tag
                or outbound.get("streamSettings", {}).get("sockopt", {}).get("dialerProxy") == outbound_tag):
            raise OpsError("outbound is shared by another chained proxy")
    for balancer in routing.get("balancers", []):
        if any(outbound_tag.startswith(prefix) for prefix in balancer.get("selector", [])):
            raise OpsError("outbound is selected by a balancer")
    outbound = build_proxy_outbound(proxy, outbound_tag)
    if indices:
        outbounds[indices[0]] = outbound
    else:
        if not outbounds:
            raise OpsError("template has no default outbound; refusing to make the new exit global")
        outbounds.append(outbound)
    kept = [r for r in rules if r != owned]
    blocked = {o.get("tag") for o in outbounds if o.get("protocol") == "blackhole"} | {"blocked", "block", "reject"}
    # Keep the leading API/security boundary, then beat domain and catch-all rules.
    index = 0
    for rule in kept:
        boundary = ((rule.get("inboundTag") == ["api"] and rule.get("outboundTag") == "api")
                    or (rule.get("outboundTag") in blocked and not rule.get("user")))
        if not boundary:
            break
        index += 1
    if any(r.get('outboundTag') in blocked and not r.get('user') for r in kept[index:]):
        raise OpsError('security rules are not a leading block; review ordering before merging')
    kept.insert(index, owned)
    routing["rules"] = kept
    return merged


def ensure_client(client: XUIClient, email: str, inbound_id: int) -> dict[str, Any]:
    all_rows = client.list_clients()
    if sum(row.get("email") == email for row in all_rows) > 1:
        raise OpsError("client email is ambiguous")
    rows = {row.get("email"): row for row in all_rows}
    row = rows.get(email)
    if row is None:
        client.create_client(email, inbound_id)
    elif inbound_id not in (row.get("inboundIds") or []):
        client.attach_client(email, inbound_id)
    result = client.get_client(email)
    if inbound_id not in (result.get("inboundIds") or []):
        raise OpsError("client was not attached to inbound after write")
    if result.get("client", result).get("enable") is False:
        raise OpsError("client is disabled; do not silently re-enable it")
    return result


def template_state(template: dict[str, Any], email: str, outbound_tag: str) -> dict[str, bool]:
    return {
        "outbound": any(item.get("tag") == outbound_tag for item in template.get("outbounds", [])),
        "routing": any(
            rule.get("outboundTag") == outbound_tag and email in (rule.get("user") or [])
            for rule in template.get("routing", {}).get("rules", [])
        ),
    }


def write_sensitive(path: str | Path, value: Any) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        content = value
    else:
        content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        os.chmod(target, 0o600)


def first_vless_link(text: str) -> str:
    match = re.search(r"vless://[^\s]+", text)
    if not match:
        raise OpsError("no VLESS link found")
    return match.group(0)


def rewrite_vless_host(link: str, public_host: str) -> str:
    parsed = urllib.parse.urlsplit(link)
    if parsed.scheme != "vless" or not parsed.username or not parsed.port:
        raise OpsError("invalid VLESS link")
    host = public_host.strip("[]")
    if ":" in host:
        host = "[%s]" % host
    netloc = "%s@%s:%d" % (parsed.username, host, parsed.port)
    return urllib.parse.urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def vless_link_uses_loopback(link: str) -> bool:
    if not link.startswith("vless://"):
        return False
    host = (urllib.parse.urlsplit(link).hostname or "").lower()
    return host in ("localhost", "127.0.0.1", "::1")


def sidecar_config_from_vless(link: str, listen_port: int) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(link)
    query = urllib.parse.parse_qs(parsed.query)
    if parsed.scheme != "vless" or not parsed.username or not parsed.hostname or not parsed.port:
        raise OpsError("invalid VLESS link")

    def one(name: str, default: str = "") -> str:
        return query.get(name, [default])[0]

    user = {
        "id": urllib.parse.unquote(parsed.username),
        "encryption": one("encryption", "none"),
    }
    if one("flow"):
        user["flow"] = one("flow")
    stream: dict[str, Any] = {
        "network": one("type", "tcp"),
        "security": one("security", "none"),
    }
    if stream["security"] == "reality":
        stream["realitySettings"] = {
            "serverName": one("sni"),
            "fingerprint": one("fp", "chrome"),
            "publicKey": one("pbk"),
            "shortId": one("sid"),
            "spiderX": one("spx", "/"),
            "show": False,
        }
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "local-socks-sidecar",
            "listen": "127.0.0.1",
            "port": listen_port,
            "protocol": "socks",
            "settings": {"auth": "noauth", "udp": True},
        }],
        "outbounds": [{
            "tag": "managed-vless",
            "protocol": "vless",
            "settings": {"vnext": [{
                "address": parsed.hostname,
                "port": parsed.port,
                "users": [user],
            }]},
            "streamSettings": stream,
        }],
        "routing": {"domainStrategy": "AsIs", "rules": []},
    }


def launchd_plist(label: str, xray_bin: str, config_path: str) -> str:
    import xml.sax.saxutils

    esc = xml.sax.saxutils.escape
    return """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array>
    <string>{xray}</string><string>run</string><string>-config</string><string>{config}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
""".format(label=esc(label), xray=esc(xray_bin), config=esc(config_path))


def remote_json(env: dict[str, str], script: str, data: Any) -> Any:
    alias = env.get("XUI_SSH_ALIAS", "")
    if not alias:
        raise OpsError("SSH alias required")
    prefix = "sudo -n " if env.get("XUI_SUDO", "0").lower() in ("1", "true", "yes") else ""
    command = prefix + "python3 -c " + shlex.quote(script)
    result = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", alias, command],
        input=json.dumps(data), text=True, capture_output=True, timeout=90,
    )
    if result.returncode:
        raise OpsError("remote check failed (output withheld to protect configuration)")
    return json.loads(result.stdout)


def backup_database(env: dict[str, str]) -> str:
    alias = env.get("XUI_SSH_ALIAS", "")
    if not alias:
        return "skipped_no_ssh_alias"
    db_path = env.get("XUI_DB_PATH", DEFAULT_DB_PATH)
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
    target = env.get("XUI_BACKUP_DIR", "/root/x-ui-backups") + "/chain-" + stamp
    remote_json(env, '''import json,sys,os,sqlite3,shutil
d=json.load(sys.stdin); os.umask(0o077); os.makedirs(d['target'],mode=0o700,exist_ok=False)
source=sqlite3.connect('file:'+d['db']+'?mode=ro',uri=True)
dest=sqlite3.connect(d['target']+'/x-ui.db'); source.backup(dest)
assert dest.execute('PRAGMA quick_check').fetchone()[0]=='ok'
dest.close(); source.close()
shutil.copyfile(d['runtime'],d['target']+'/config.json')
for name in ('x-ui.db','config.json'): os.chmod(d['target']+'/'+name,0o600)
print(json.dumps({'ok':True}))
''', {"db": db_path, "runtime": env.get("XUI_RUNTIME_CONFIG", DEFAULT_RUNTIME_CONFIG), "target": target})
    return target


def read_runtime(env: dict[str, str]) -> dict[str, Any]:
    return remote_json(env, "import json,sys; print(open(json.load(sys.stdin)['path']).read())",
                       {"path": env.get("XUI_RUNTIME_CONFIG", DEFAULT_RUNTIME_CONFIG)})


def without_chain(config: dict[str, Any], email: str, tag: str) -> dict[str, Any]:
    result = copy.deepcopy(config)
    result['outbounds'] = [o for o in result.get('outbounds', []) if o.get('tag') != tag]
    result.setdefault('routing', {})['rules'] = [r for r in result.get('routing', {}).get('rules', [])
                                                 if r.get('outboundTag') != tag]
    for inbound in result.get('inbounds', []):
        settings = unwrap_json(inbound.get('settings', {}))
        if 'clients' in settings:
            settings['clients'] = [c for c in settings['clients'] if c.get('email') != email]
            inbound['settings'] = settings
    return result


def verify_runtime_via_ssh(env: dict[str, str], email: str, outbound_tag: str,
                           expected: dict[str, Any], baseline: dict[str, Any], identity: str) -> bool:
    if not env.get("XUI_SSH_ALIAS"):
        return False
    runtime = read_runtime(env)
    actual = [o for o in runtime.get('outbounds', []) if o.get('tag') == outbound_tag]
    wanted = [o for o in expected.get('outbounds', []) if o.get('tag') == outbound_tag]
    users = [c for b in runtime.get('inbounds', []) for c in unwrap_json(b.get('settings', {})).get('clients', [])]
    return (actual == wanted and len(actual) == 1
            and runtime.get('routing') == expected.get('routing')
            and any(c.get('email') == email and c.get('id') == identity for c in users)
            and without_chain(runtime, email, outbound_tag) == without_chain(baseline, email, outbound_tag))


def verify_upstream(env: dict[str, str], proxy: dict[str, Any], expected_ip: str) -> None:
    result = remote_json(env, '''import json,sys,subprocess
d=json.load(sys.stdin); p=d['proxy']; scheme='socks5h' if p['protocol'] in ('socks','socks5') else 'http'
cfg='proxy = '+json.dumps(scheme+'://'+p['host']+':'+str(p['port']))+'\\n'
cfg+='proxy-user = '+json.dumps(p['username']+':'+p['password'])+'\\n'
ok=[]
for url in ('https://api.ipify.org','https://checkip.amazonaws.com'):
 r=subprocess.run(['curl','--config','-','--noproxy','','-4fsS','--connect-timeout','8','--max-time','20',url],
                  input=cfg,text=True,capture_output=True,timeout=25)
 ok.append(r.returncode==0 and r.stdout.strip()==d['expected'])
print(json.dumps({'ok':all(ok)}))
''', {'proxy': proxy, 'expected': expected_ip})
    if not result.get('ok'):
        raise OpsError('upstream authentication or expected exit check failed from VPS; no changes made')


def verify_exit(link: str, expected_ip: str, xray_bin: str, curl_bin: str) -> str:
    with tempfile.TemporaryDirectory(prefix="chain-egress-") as tmp:
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        config_path = Path(tmp) / "sidecar.json"
        write_sensitive(config_path, sidecar_config_from_vless(link, port))
        process = subprocess.Popen(
            [xray_bin, "run", "-config", str(config_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(40):
                if process.poll() is not None:
                    raise OpsError("temporary Xray sidecar exited")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                        break
                except OSError:
                    time.sleep(0.2)
            else:
                raise OpsError("temporary Xray sidecar did not become ready")
            output = subprocess.check_output([
                curl_bin, "--noproxy", "", "--ipv4", "--fail", "--silent", "--show-error", "--max-time", "30",
                "--proxy", "socks5h://127.0.0.1:%d" % port,
                "https://api.ipify.org",
            ], text=True).strip()
            if output != expected_ip:
                raise OpsError("end-to-end exit mismatch; delivery is not accepted")
            return output
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@contextlib.contextmanager
def connected_client(env: dict[str, str]) -> Iterator[XUIClient]:
    env = dict(env)
    env.setdefault("XUI_USER", env.get("XUI_ADMIN_USER", ""))
    env.setdefault("XUI_PASS", env.get("XUI_ADMIN_PASS", ""))
    env.setdefault("XUI_PORT", env.get("XUI_WEB_PORT", ""))
    required(env, "XUI_USER", "XUI_PASS")
    insecure = env.get("XUI_INSECURE", "0").lower() in ("1", "true", "yes")
    if env.get("XUI_BASE_URL"):
        client = XUIClient(env["XUI_BASE_URL"], env["XUI_USER"], env["XUI_PASS"], insecure)
        client.login()
        yield client
        return

    required(env, "XUI_PORT", "XUI_WEB_BASE_PATH")
    scheme = env.get("XUI_SCHEME", "http")
    base_path = "/" + env["XUI_WEB_BASE_PATH"].strip("/")
    alias = env.get("XUI_SSH_ALIAS", "")
    if alias:
        with ssh_tunnel(alias, int(env["XUI_PORT"])) as local_port:
            client = XUIClient("%s://127.0.0.1:%d%s" % (scheme, local_port, base_path),
                               env["XUI_USER"], env["XUI_PASS"], insecure)
            client.login()
            yield client
    else:
        required(env, "XUI_HOST")
        client = XUIClient("%s://%s:%s%s" % (scheme, env["XUI_HOST"], env["XUI_PORT"], base_path),
                           env["XUI_USER"], env["XUI_PASS"], insecure)
        client.login()
        yield client


def verify_regressions(args: argparse.Namespace) -> list[str]:
    if not args.regression_manifest:
        return []
    path = Path(args.regression_manifest).expanduser()
    results = []
    for item in json.loads(path.read_text(encoding="utf-8")):
        link_path = Path(item['link_file']).expanduser()
        if not link_path.is_absolute():
            link_path = path.parent / link_path
        link = first_vless_link(link_path.read_text(encoding="utf-8"))
        verify_exit(link, item['expected_exit_ip'], args.xray_bin, args.curl_bin)
        results.append(item['name'])
    return results


def command_chain_upsert(args: argparse.Namespace) -> int:
    xui_env = load_env(args.xui_env)
    if args.ssh_alias:
        xui_env["XUI_SSH_ALIAS"] = args.ssh_alias
    if not args.dry_run:
        if not args.expected_exit_ip:
            raise OpsError("--expected-exit-ip is required for deployment")
        if not xui_env.get("XUI_SSH_ALIAS") and not args.allow_api_only:
            raise OpsError("SSH required for backup, upstream preflight and runtime verification")
        if not shutil.which(args.xray_bin) or not shutil.which(args.curl_bin):
            raise OpsError('local Xray and curl are required for acceptance; install them before deployment')
    if args.public_host and (args.public_host.strip('[]').lower() in ('localhost', '127.0.0.1', '::1', '0.0.0.0', '::')
                            or re.search(r'[/\s?#@]', args.public_host)):
        raise OpsError('--public-host must be the public entry hostname or IP, without a scheme or path')
    proxy = proxy_from_env(load_env(args.proxy_env), args.proxy_prefix)
    with connected_client(xui_env) as client:
        envelope = client.xray_envelope()
        template = unwrap_json(envelope["xraySetting"])
        inbounds = client.inbounds()
        inbound = next((b for b in inbounds if b['id'] == args.inbound_id), None)
        if not inbound:
            raise OpsError("selected inbound does not exist")
        validate_inbound(inbound)
        rows = [r for r in client.list_clients() if r.get('email') == args.client_email]
        if len(rows) > 1 or (rows and set(rows[0].get('inboundIds', [])) != {args.inbound_id}):
            raise OpsError("client email is shared or belongs to another inbound; choose a new one")
        if rows and rows[0].get('client', rows[0]).get('enable') is False:
            raise OpsError("existing client is disabled; no changes made")
        if client.api_generation == 'legacy':
            # Reject unsupported export settings before making any server writes.
            legacy_vless_link(inbound, {'id': 'preflight', 'email': args.client_email})
            if not args.public_host:
                raise OpsError("legacy export requires --public-host (the VPS entry, not the proxy exit)")
        merged = merge_chain_egress(template, proxy, args.client_email, args.outbound_tag)
        before = template_state(template, args.client_email, args.outbound_tag)
        if args.dry_run:
            print(json.dumps({
                "dry_run": True,
                "api_generation": client.api_generation,
                "client_email": args.client_email,
                "inbound_id": args.inbound_id,
                "outbound_tag": args.outbound_tag,
                "existing_state": before,
                "writes": 0,
            }, indent=2))
            return 0

        baseline = read_runtime(xui_env) if xui_env.get('XUI_SSH_ALIAS') else {}
        if baseline:
            verify_upstream(xui_env, proxy, args.expected_exit_ip)
        verify_regressions(args)
        backup = backup_database(xui_env)
        write_sensitive(str(Path(args.output).expanduser()) + '.before.json', {
            'template': template, 'inbounds': inbounds, 'runtime': baseline, 'backup': backup,
            'client_email': args.client_email, 'outbound_tag': args.outbound_tag,
            'client_existed': bool(rows), 'api_generation': client.api_generation,
        })
        if unwrap_json(client.xray_envelope()['xraySetting']) != template:
            raise OpsError('template changed during preflight; stopped before writes')
        # Persist the user route first so a new client never inherits the default exit.
        client.update_xray_template(merged, envelope.get("outboundTestUrl", DEFAULT_TEST_URL))
        client_info = ensure_client(client, args.client_email, args.inbound_id)
        client.force_restart_xray()
        time.sleep(args.restart_wait)

        final_envelope = client.xray_envelope()
        final_template = unwrap_json(final_envelope["xraySetting"])
        state = template_state(final_template, args.client_email, args.outbound_tag)
        final_client = client.get_client(args.client_email)
        if (final_template != merged or not all(state.values())
                or args.inbound_id not in (final_client.get("inboundIds") or [])):
            raise OpsError("persisted template/client readback failed after force restart")

        links = client.client_links(args.client_email)
        if args.public_host:
            links = [rewrite_vless_host(link, args.public_host) if link.startswith("vless://") else link for link in links]
        if not links:
            raise OpsError("3x-ui returned no client links")
        if any(vless_link_uses_loopback(link) for link in links):
            raise OpsError("generated VLESS link uses loopback; pass --public-host")
        vless = next((link for link in links if link.startswith('vless://')), '')
        if not vless:
            raise OpsError('export returned no VLESS link')
        identity = urllib.parse.unquote(urllib.parse.urlsplit(vless).username or '')
        runtime_ok = verify_runtime_via_ssh(xui_env, args.client_email, args.outbound_tag, merged, baseline, identity)
        if not runtime_ok and xui_env.get('XUI_SSH_ALIAS'):
            raise OpsError('runtime/client identity or unrelated configuration changed; stop and inspect private backup')
        delivery = {
            "client_email": args.client_email,
            "inbound_id": args.inbound_id,
            "outbound_tag": args.outbound_tag,
            "client": client_info.get("client", final_client.get("client", {})),
            "links": links,
            "verified": False,
        }
        write_sensitive(args.output, delivery)
        exit_result = verify_exit(vless, args.expected_exit_ip, args.xray_bin, args.curl_bin)
        regressions = verify_regressions(args)
        delivery.update(verified=True, observed_exit=exit_result, regression_passed=regressions,
                        runtime_verified=runtime_ok, api_generation=client.api_generation, backup=backup)
        write_sensitive(args.output, delivery)
        write_sensitive(str(Path(args.output).expanduser()) + '.vless.txt', vless + '\n')

        print(json.dumps({
            "ok": True,
            "api_generation": client.api_generation,
            "client_email": args.client_email,
            "outbound_tag": args.outbound_tag,
            "backup": backup,
            "persisted_readback": state,
            "runtime_readback": "pass" if runtime_ok else "skipped_api_only",
            "link_count": len(links),
            "delivery_file": str(Path(args.output).expanduser()),
            "end_to_end_exit": exit_result,
            "regression_passed": regressions,
        }, indent=2))
    return 0


def command_summary(args: argparse.Namespace) -> int:
    env = load_env(args.xui_env)
    if args.ssh_alias:
        env["XUI_SSH_ALIAS"] = args.ssh_alias
    with connected_client(env) as client:
        envelope = client.xray_envelope()
        template = unwrap_json(envelope["xraySetting"])
        print(json.dumps({
            "api_generation": client.api_generation,
            "clients": len(client.list_clients()),
            "outbound_tags": [item.get("tag") for item in template.get("outbounds", [])],
            "routing_rules": len(template.get("routing", {}).get("rules", [])),
        }, indent=2))
    return 0


def command_render_sidecar(args: argparse.Namespace) -> int:
    text = Path(args.link_file).expanduser().read_text(encoding="utf-8")
    link = first_vless_link(text)
    output = Path(args.output).expanduser()
    write_sensitive(output, sidecar_config_from_vless(link, args.listen_port))
    result = {"config": str(output), "listen": "127.0.0.1:%d" % args.listen_port}
    if args.launchd_output:
        plist_path = Path(args.launchd_output).expanduser()
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        plist_path.write_text(launchd_plist(args.label, args.xray_bin, str(output)), encoding="utf-8")
        os.chmod(plist_path, 0o644)
        result["launchd_plist"] = str(plist_path)
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    summary = subparsers.add_parser("summary", help="Read a sanitized panel summary")
    summary.add_argument("--xui-env", required=True)
    summary.add_argument("--ssh-alias", default="", help="Override XUI_SSH_ALIAS from the env file")
    summary.set_defaults(func=command_summary)

    chain = subparsers.add_parser("chain-upsert", help="Persist one client-specific proxy egress")
    chain.add_argument("--xui-env", required=True)
    chain.add_argument("--ssh-alias", default="", help="Override XUI_SSH_ALIAS from the env file")
    chain.add_argument("--proxy-env", required=True)
    chain.add_argument("--proxy-prefix", required=True, help="Env prefix such as IPNEW")
    chain.add_argument("--inbound-id", required=True, type=int)
    chain.add_argument("--client-email", required=True)
    chain.add_argument("--outbound-tag", required=True)
    chain.add_argument("--output", required=True, help="Mode-0600 JSON delivery path")
    chain.add_argument("--public-host", default="", help="Rewrite generated VLESS links to this public host")
    chain.add_argument("--expected-exit-ip", default="", help="Required for deployment, optional for dry-run")
    chain.add_argument("--regression-manifest", default="", help="Private JSON list of existing name/link_file/expected_exit_ip probes")
    chain.add_argument("--xray-bin", default="xray")
    chain.add_argument("--curl-bin", default="curl")
    chain.add_argument("--restart-wait", type=float, default=3.0)
    chain.add_argument("--allow-api-only", action="store_true")
    chain.add_argument("--dry-run", action="store_true")
    chain.set_defaults(func=command_chain_upsert)

    sidecar = subparsers.add_parser("render-sidecar", help="Render a local SOCKS sidecar from a VLESS link")
    sidecar.add_argument("--link-file", required=True)
    sidecar.add_argument("--listen-port", required=True, type=int)
    sidecar.add_argument("--output", required=True)
    sidecar.add_argument("--launchd-output", default="")
    sidecar.add_argument("--label", default="com.example.xray-sidecar")
    sidecar.add_argument("--xray-bin", default="xray")
    sidecar.set_defaults(func=command_render_sidecar)
    return parser


def main() -> int:
    try:
        args = build_parser().parse_args()
        return args.func(args)
    except (OpsError, OSError, ValueError, subprocess.SubprocessError) as error:
        message = str(error) if isinstance(error, OpsError) else type(error).__name__ + ' (details withheld)'
        print("error: %s" % message, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
