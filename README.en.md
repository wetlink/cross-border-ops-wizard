# VPS Operations Wizard / cross-border-ops-wizard

[中文](README.md) | English

Current version: `0.6.0`

`cross-border-ops-wizard` manages the access-asset lifecycle for teams maintaining cross-border tooling. It covers freshly provisioned overseas VPS hosts, DNS, certificates, x-ui / 3x-ui, node delivery, and maintenance. It also covers newly purchased residential/static proxies from validation through client-specific VPS egress and mobile VLESS delivery to AdsPower, RoxyBrowser, or BitBrowser profile association and in-browser exit verification. **Tencent Cloud Lighthouse ships as a VPS profile**; other clouds and proxy providers use the same asset model.

It focuses on the full path from "provisioned" to "deployed, verified, handed over, and maintainable", and works across **Claude Code, Codex, WorkBuddy, and OpenClaw**. This repository only contains methods, templates, and check scripts; it does not contain real server credentials, admin URLs, or private links.

## Use Cases

- Standardize onboarding for a freshly provisioned overseas VPS on any provider (Lighthouse as a built-in profile).
- Bind a purchased domain to the VPS and configure HTTPS (an IP-only path is supported when there is no domain).
- Deploy an x-ui / 3x-ui management panel so the team can use and maintain cross-border tooling.
- Configure DNS, certificates, HTTPS gateway, panel entry, and health checks.
- Troubleshoot unreachable nodes, certificate issues, closed ports, and slow/lossy paths.
- Triage VLESS/Reality EOF, Clash/Mihomo fake-ip, and client hot-reload persistence failures.
- Validate a purchased residential/static proxy, its observed exit, and multi-A gateway health.
- Add a client-specific purchased exit behind an existing VLESS/Reality VPS.
- Add reusable proxies to AdsPower/RoxyBrowser/BitBrowser, associate profiles, and verify the in-browser exit.
- Handle AdsPower loopback-check false negatives with a persistent local Xray sidecar.
- Generate a team handover runbook and sensitive-information checklist.
- Turn deployment, verification, handover, and maintenance into a reusable SOP.

## Core Capabilities

- Provider-agnostic pre-purchase planning checklist for an overseas VPS and domain.
- Target host identity verification and SSH onboarding.
- DNS and certificate checks.
- x-ui admin-panel deployment flow, entry model, and account handover boundaries.
- One-click node engine `scripts/node-wizard.sh` (deploy/verify/panel-open/panel-close/links/rollback).
- Legacy x-ui and modern 3x-ui chained-egress tool `scripts/xui_chain_egress.py` (read-only API detection, VPS upstream preflight, consistent backup, isolated routes, forced restart, runtime readback, and verified VLESS export).
- Public/private port boundary design.
- Service, log, network, and team-availability verification.
- Local runbook and sensitive handover skeleton generation.
- Fingerprint-browser acceptance from global inventory through profile association and readback.
- Confirmation and rollback discipline before changes.

## Repository Layout

```text
.
├── README.md
├── README.en.md
├── LICENSE
├── CHANGELOG.md
├── VERSION
├── docs/
│   └── superpowers/          # design spec + implementation plan for the engine
├── references/
│   ├── documentation.md
│   ├── chain-egress.md
│   ├── fingerprint-browser-egress.md
│   ├── sop.md
│   └── verification.md
├── scripts/
│   ├── install.sh
│   ├── node-wizard.sh        # one-click node engine entrypoint
│   ├── xui_chain_egress.py   # 3x-ui chained egress and local sidecar
│   ├── lib/                  # engine libraries (secrets/preflight/config/verify/deploy/panel/rollback…)
│   ├── render_node_materials.py
│   └── validate_skill_package.py
├── tests/                    # zero-dependency bash tests (tests/run.sh runs all)
└── skill/
    └── cross-border-ops-wizard/
        └── SKILL.md
```

## VPS Chain to a VLESS Link

Use an existing SSH-managed VPS with an enabled VLESS TCP/Reality inbound and
an authenticated SOCKS5 or HTTP upstream. The path is:

```text
device -> your VPS VLESS/Reality inbound -> dedicated user route -> purchased exit
```

Follow the [private env schemas and deployment guide](references/chain-egress.md).
Run `chain-upsert --dry-run` first, confirm the target and core restart window,
then apply with `--expected-exit-ip`. Supply `--public-host` for legacy panels.
A successful run writes a mode-0600 delivery JSON and `.json.vless.txt`; existing
Clash selections, AI routes and browser profiles are not switched.
Use `--regression-manifest` to probe protected exits before and after deployment.

Supported API families are the legacy 2.x-style `/panel/xray/` plus
`inbounds/addClient`, and modern 3.x client APIs. Detection falls back only on
a read-only 404, never on authentication errors. Other panel forks/transports
need separate adaptation. Release tests use synthetic local HTTP fixtures,
not production VPS writes.

## Quick Check

```bash
python3 scripts/validate_skill_package.py
python3 scripts/render_node_materials.py --help
python3 scripts/xui_chain_egress.py --help
python3 scripts/check_public_safety.py
tests/run.sh
```

## Skill Installation (multi-agent, one shot)

`scripts/install.sh` assembles a self-contained skill bundle from source and installs it
into whichever agent skills dirs exist on this machine (Claude Code `~/.claude/skills`,
Codex `~/.codex/skills`, WorkBuddy `~/.workbuddy/skills`, OpenClaw `~/.openclaw/skills`,
shared `~/.agents/skills`):

```bash
scripts/install.sh            # install into agent dirs that already exist
scripts/install.sh --all      # create + install for every known agent
scripts/install.sh --dry-run  # preview targets only
scripts/install.sh --dest ~/.some-agent/skills   # explicit dir
```

Each run repackages from `SKILL.md + references/ + scripts/`, so it never ships a stale zip.

## License

MIT
