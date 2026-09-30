# Changelog

All notable changes to `cross-border-ops-wizard` are documented here.
Versioning follows [SemVer](https://semver.org/). Each release is also a git tag.

## [0.6.0] - 2026-09-30

### Added
- Legacy x-ui template/client API compatibility, read-only 404 detection and
  VLESS Reality export from persisted panel parameters without key rotation.
- VPS-side upstream exit preflight, consistent SQLite backup plus runtime
  snapshot, non-root SSH support via `XUI_SUDO=1`, and optional protected-route
  regression manifests.
- Verified plain VLESS link files, sanitized HTTP workflow fixtures for both
  API generations, public-material safety checks and a CI test workflow.

### Fixed
- Place dedicated user rules before domain/catch-all rules while preserving
  leading API/security rules. Reject shared routes, reserved/default outbounds,
  ambiguous clients, and outbound dependencies instead of overwriting them.
- Stop before writes when required verification inputs are missing, the
  upstream check fails, or the template changes during preflight.
- Read back exact template/routing/outbound/client identity and compare
  unrelated runtime state; do not accept tag existence alone.
- Suppress potentially sensitive panel/transport error payloads and exclude
  Python bytecode from distributable skill packages.

### Changed
- Real deployments now require `--expected-exit-ip`; API-only mode must be
  explicitly selected and records missing SSH verification.
- This release was tested with offline HTTP fixtures. No production VPS was
  modified during release validation.

## [0.5.0] - 2026-07-14

### Added
- `scripts/xui_chain_egress.py` for 3x-ui 3.x client-specific chained exits,
  including dry-run, remote database backup, idempotent client/outbound/routing
  writes, official client-link export, forced restart, runtime readback, and
  optional end-to-end exit verification.
- Local Xray SOCKS sidecar rendering from a VLESS/Reality link, with optional
  macOS LaunchAgent generation for fingerprint browsers that cannot reach the
  provider gateway directly.
- A chained-egress reference covering private env schemas, persistence gates,
  asset fields, and failure recovery.
- BitBrowser onboarding and browser-edition capacity/lifecycle guidance.
- Regression tests for the 3x-ui form endpoint, client API paths, idempotent
  template merge, sidecar rendering, sensitive-file permissions, and release
  metadata synchronization.

### Changed
- Made a force restart plus generated runtime-config readback mandatory for
  chained routes; a successful hot apply is no longer accepted as persistence.
- Made in-browser public-IP verification authoritative when AdsPower or another
  manager reports a false negative for a loopback sidecar.
- Expanded asset handover guidance with first-hop VPS, outbound tag, VLESS
  client, browser environment, replacement relationship, and write-readback
  fields.

## [0.4.0] - 2026-07-12

### Added
- Fingerprint-browser egress onboarding for purchased residential/static proxies.
- Global-first AdsPower and RoxyBrowser workflows with profile-association readback.
- Multi-A proxy gateway diagnosis and in-browser exit acceptance criteria.
- Regression test for the global-proxy and credential-safety contract.

### Changed
- Expanded the Skill from VPS-only onboarding to the connected lifecycle of VPS
  nodes, purchased exits, and fingerprint-browser environments.
- Moved version tracking exclusively to `VERSION` and `CHANGELOG.md` so the
  Skill frontmatter follows the current schema.

## [0.3.1] - 2026-06-29

### Fixed
- Changed the default Reality SNI from `www.microsoft.com` to `www.apple.com`.
- Added `REALITY_DEST` so deployments can pin a validated target separately
  from the client-facing SNI.
- Persisted Reality SNI/dest into `/root/ops-secrets/<alias>.env` for future
  idempotent runs.

### Added
- Incident triage guidance for service state, direct `curl --noproxy '*'`,
  Clash/Mihomo fake-ip, Reality EOF, and client configuration persistence.
- Tests for default Reality SNI/dest and explicit target overrides.

## [0.3.0] - 2026-06-26

### Added
- `scripts/node-wizard.sh` one-click engine with subcommands: `deploy`, `verify`,
  `panel-open`, `panel-close`, `links`, `rollback`.
- Idempotent provisioning of xray VLESS Reality (443) + x-ui panel bound to
  localhost (public admin gateway only on demand via `panel-open`).
- Semi-auto preflight gate (DNS + cloud firewall) that prints an actionable
  checklist and exits when the manual cloud step is not yet done.
- Zero-dependency bash test harness under `tests/` (10 suites).
- Library split under `scripts/lib/` (common, secrets, links, preflight, config,
  verify, deploy, panel, rollback).

### Fixed (from final review, pre-real-VPS hardening)
- Idempotent re-run: `deploy` now reuses existing per-node secrets instead of
  regenerating them (was invalidating client subscriptions).
- Robust entrypoint path resolution + multi-file shipping model documented
  (engine is entrypoint + `lib/`; sync `scripts/` to the host then run).
- Cert phase reordered after firewall, guarded against re-issue, and frees port 80
  for the standalone HTTP-01 challenge.
- nginx gateway uses HTTP upstream to the x-ui panel, adds the `/sub/` route, and
  writes `/etc/nginx/ops.htpasswd`; x-ui panel bound to `127.0.0.1`.

> Note: some real-VPS specifics (exact 3x-ui setting flags, acme mode, port
> behaviors) still require validation in the Task 12 real-VPS acceptance run.
> Follow-up (2026-07-07): the engine has since been exercised on a real VPS
> (v0.3.0 final-review hardening) and through a real production incident
> (v0.3.1). Per-step acceptance status is recorded in
> `docs/superpowers/plans/2026-06-26-one-click-node-engine.md` ("真机受入记录").

### Changed
- Rewrote `SKILL.md` `description` to trigger-style ("Use when…"), dropped the
  workflow summary, and removed the Tencent-Lighthouse lock-in. The skill is now
  provider-agnostic, with Lighthouse kept as a built-in profile.
- Generalized `README.md` / `README.en.md` to "any overseas VPS" and multi-agent.

### Added
- `scripts/install.sh`: one-shot installer that assembles a self-contained bundle
  from source and installs into Claude Code, Codex, WorkBuddy, OpenClaw, and the
  shared `~/.agents` skills directories.
- `references/verification.md`: "Route / Packet-Loss Diagnosis" section for
  troubleshooting slow/lossy downloads (server-side vs path-side localization).
- `version` field in `SKILL.md` frontmatter.

### Removed
- Committed `cross-border-ops-wizard.zip` build artifact. It is now gitignored;
  regenerate on demand via `validate_skill_package.py --zip` or `install.sh`.

## [0.1.0] - initial

- Initial open-source release: SOP, verification, and documentation references,
  plus `render_node_materials.py` and `validate_skill_package.py`.
