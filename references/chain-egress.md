# Chained Proxy Egress Through x-ui / 3x-ui

Use this module when a phone, browser, or automation client must enter through
an existing VLESS/Reality VPS and leave through a purchased static or
residential proxy:

```text
client -> VLESS/Reality VPS -> client-specific Xray outbound -> purchased exit
```

The acceptance target is persistence and observed egress, not an API success
message or a temporary hot-loaded route.

## 1. Private Inputs

Keep panel and proxy credentials in mode-0600 env files outside the repository.
The panel env supports either `XUI_BASE_URL` or an SSH-tunnel configuration:

```text
XUI_USER=<secret>
XUI_PASS=<secret>
XUI_SCHEME=http
XUI_PORT=<panel-port>
XUI_WEB_BASE_PATH=<random-panel-path>
XUI_SSH_ALIAS=<ssh-config-alias>
XUI_RUNTIME_CONFIG=/usr/local/x-ui/bin/config.json
XUI_DB_PATH=/etc/x-ui/x-ui.db
XUI_SUDO=1
```

`XUI_SUDO=1` uses non-interactive sudo for a managed non-root SSH account;
omit it for root. Set `XUI_INSECURE=1` only when you deliberately accept a
self-signed panel certificate over the verified SSH tunnel. The script does
not change server keys, firewall rules, system proxy settings or AI defaults.

Store one or more proxy tuples in a separate env file. Prefix each tuple so a
single file can hold several purchased exits:

```text
IPNEW_PROTOCOL=socks5
IPNEW_HOST=<provider-gateway>
IPNEW_PORT=<gateway-port>
IPNEW_USER=<secret>
IPNEW_PASS=<secret>
IPNEW_EXIT_IP=<expected-public-ip>
```

Never put these files, generated links, panel paths, or real purchased IPs in a
public repository.

## 2. Preflight

Before changing 3x-ui:

1. Back up the panel database and verify the backup can be read.
2. Test the purchased proxy from the VPS itself.
3. Test every protocol the provider claims to support; SOCKS5 and HTTP may
   behave differently even with the same credentials.
4. Require the observed public IP to equal the purchased exit IP.
5. Record the provider gateway separately from the observed exit.
6. Confirm the intended VLESS inbound ID, client name, and outbound tag.

Do not continue from a local-laptop-only proxy test. Providers may allow their
gateway from the VPS while rejecting the operator's current network, or the
reverse.

## 3. API Families and Persistence Contract

Identify the family with a read-only template request. Only a 404 from
`POST /panel/api/xray/` permits fallback to `POST /panel/xray/`. A 401, 403,
timeout, malformed response or 5xx is not a reason to try writes on another API.
The helper uses one detected family for the rest of the run.

Legacy 2.x-style x-ui uses:

```text
POST /panel/xray/                    read template envelope
POST /panel/xray/update              form-encoded xraySetting + outboundTestUrl
GET  /panel/api/inbounds/list        persisted client and Reality settings
POST /panel/api/inbounds/addClient   form id + settings={"clients":[...]}
```

Clients must be registered through the API, never by editing the inbound JSON
in SQLite: raw DB writes can omit traffic registration. Legacy VLESS export
uses the persisted client ID and **public** Reality parameters; a private key
must never enter a share link. A public VPS host is mandatory because a local
panel tunnel is not a usable public entry. Do not rotate keys to fill a missing
public-key field; stop and inspect the actual panel variant.

Modern 3x-ui stores clients as first-class records. Use the current client API:

```text
POST /panel/api/clients/add
POST /panel/api/clients/:email/attach
GET  /panel/api/clients/get/:email
GET  /panel/api/clients/links/:email
```

The Xray template endpoint has a different body contract:

```text
POST /panel/api/xray/update
Content-Type: application/x-www-form-urlencoded
xraySetting=<complete-json-template>
outboundTestUrl=<probe-url>
```

Sending JSON to this endpoint is not equivalent. Preserve all unrelated
outbounds and routing rules, replace only the target outbound/rule, and keep
private-address blocking rules ahead of the client-specific route.

After saving, call the force restart endpoint:

```text
POST /panel/api/server/restartXrayService
```

Then read the persisted template, client attachment, and generated runtime
config. A hot apply that works before restart is not a persistence result.

## 4. Deterministic Tool

Prerequisites: Python 3.10+, local Xray and curl on PATH (or explicit
`--xray-bin` / `--curl-bin` paths), remote Python 3 and curl, and an authorized
SSH account with read/backup access to x-ui files. The program checks local
executables before real writes. Avoid simultaneous panel/config edits during
deployment; the template drift check cannot provide a server-side transaction.

Preview without writes:

```bash
python3 scripts/xui_chain_egress.py chain-upsert \
  --xui-env ~/.config/vps-ops/node-x-ui.env \
  --ssh-alias managed-node \
  --proxy-env ~/.config/vps-ops/proxy-chains.env \
  --proxy-prefix IPNEW \
  --inbound-id 1 \
  --client-email phone-new \
  --outbound-tag phone_exit_new \
  --output ~/.config/vps-ops/phone-new-delivery.json \
  --dry-run
```

Apply and require a full end-to-end exit check:

```bash
python3 scripts/xui_chain_egress.py chain-upsert \
  --xui-env ~/.config/vps-ops/node-x-ui.env \
  --ssh-alias managed-node \
  --proxy-env ~/.config/vps-ops/proxy-chains.env \
  --proxy-prefix IPNEW \
  --inbound-id 1 \
  --client-email phone-new \
  --outbound-tag phone_exit_new \
  --public-host node.example.test \
  --expected-exit-ip "$EXPECTED_EXIT_IP" \
  --xray-bin ~/.local/bin/xray \
  --output ~/.config/vps-ops/phone-new-delivery.json
```

The tool is idempotent for the same client email and outbound tag. It creates a
remote database backup when `XUI_SSH_ALIAS` exists, writes delivery material
mode `0600`, never prints links, and fails unless post-restart readback passes.
Real writes require `--expected-exit-ip`, plus SSH by default. The script tests
the configured upstream protocol from the VPS against two IP echo services,
backs up SQLite using its backup API and verifies integrity, then saves the
runtime config. It writes a private `<output>.before.json` local snapshot too.
For a new user it persists the route before registering the client, so the new
identity cannot transiently inherit the default exit.

Use `--allow-api-only` only when SSH is genuinely unavailable and the user
accepts missing remote backup, VPS upstream preflight and runtime readback.
An actual SSH readback failure still fails; the flag is not a bypass for a
failed check. Record the downgrade as an unresolved verification gap.

The successful delivery includes `<output>.vless.txt`. The JSON starts with
`verified: false` until exit and configured regression probes pass. Never
deliver a failed run as ready. `verified` is an egress-test result, not proof of
residential ownership, account eligibility or platform-policy compliance.

### Protect Existing Routes

Give the new chain a unique client email and outbound tag. The merge rejects
shared user/domain rules, reserved/default outbound tags, other proxy
dependencies, balancer use, and client identities shared across inbounds.
It inserts the dedicated route after the leading API/security block and before
domain or catch-all rules, preserving unrelated order and content. Existing
unusual security-rule ordering needs manual review rather than a guessed merge.

For each important existing AI/default exit, create a private manifest outside
the repository (documentation IPs below are placeholders):

```json
[
  {
    "name": "existing-ai-route",
    "link_file": "existing-ai.vless.txt",
    "expected_exit_ip": "198.51.100.20"
  }
]
```

Pass `--regression-manifest ~/.config/vps-ops/protected-routes.json`.
Relative `link_file` paths resolve beside the manifest. Those VLESS routes are
probed before and after deployment. Also check the real application path if it
uses a local rule engine: a VLESS probe does not prove what Clash selected.

### Failure and Narrow Rollback

Do not keep retrying mutations after an ambiguous write or verification error.
Read the template, client and runtime first. Keep the private snapshots.
This command does not automatically roll back partial writes. With rollback
authorization, remove only the newly created client's UUID through the client
API (legacy: `POST /panel/api/inbounds/{id}/delClient/{uuid}`), then remove only
its exact dedicated rule and outbound from the **current** template, save and
force restart. Check for later dependencies before removing anything. If the
client/chain existed before this run, restore only its owned pre-change state,
not the entire server. Recheck old exits after rollback.

Do not restore an old whole-database backup over unrelated later changes.

## 5. Browser Sidecar

Some fingerprint browsers cannot reach the provider gateway directly, or their
proxy manager cannot test a loopback address. Render a local SOCKS endpoint
from the verified VLESS link:

```bash
python3 scripts/xui_chain_egress.py render-sidecar \
  --link-file ~/.config/vps-ops/phone-new-links.txt \
  --listen-port 19123 \
  --output ~/.config/vps-ops/phone-new-sidecar.json \
  --launchd-output ~/Library/LaunchAgents/com.example.phone-new.plist \
  --label com.example.phone-new \
  --xray-bin ~/.local/bin/xray
```

Load the generated service only after checking that the selected port is free.
The browser should use `socks5://127.0.0.1:<port>`. The browser manager's
loopback test is not authoritative; open the real environment and verify its
public IP from inside the browser.

## 6. Acceptance Harness

All of these must pass:

```text
[ ] proxy authentication from the VPS returns expected_exit_ip
[ ] client record exists and is attached to the intended inbound
[ ] persisted template contains the target outbound and routing rule
[ ] force restart succeeds
[ ] generated runtime config still contains client, outbound, and rule
[ ] modern client-link endpoint or legacy persisted parameters produce a usable VLESS link
[ ] end-to-end VLESS request returns expected_exit_ip
[ ] fingerprint browser returns expected_exit_ip when browser setup was requested
[ ] credentials and links exist only in approved mode-0600 storage
[ ] asset inventory write is followed by a readback
```

## 7. Asset Record

Keep non-secret fields in the operational inventory or Base table:

- provider and product type
- expected and observed exit IP
- country, city, timezone, ASN, and quality rating
- first-hop VPS alias
- Xray outbound tag and VLESS client email
- fingerprint-browser name and environment name
- credential index, never the credential value
- replacement relationship and renewal date
- last verification time and actual-exit acceptance flag

For Base or other remote inventory writes, run a dry-run where supported, then
perform the write and read the same record back before reporting completion.
