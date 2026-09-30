#!/usr/bin/env bash
set -u
. "$(dirname "$0")/lib.sh"

root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(cat "$root/VERSION")"
assert_eq "release version" "$version" "0.6.0"
assert_contains "Chinese README version" "$(cat "$root/README.md")" '当前版本：`0.6.0`'
assert_contains "English README version" "$(cat "$root/README.en.md")" 'Current version: `0.6.0`'
assert_contains "changelog release" "$(cat "$root/CHANGELOG.md")" '## [0.6.0] - 2026-09-30'
assert_contains "skill chain reference" "$(cat "$root/skill/cross-border-ops-wizard/SKILL.md")" 'references/chain-egress.md'
assert_contains "skill chain tool" "$(cat "$root/skill/cross-border-ops-wizard/SKILL.md")" 'scripts/xui_chain_egress.py'

finish
