#!/usr/bin/env bash
set -u
. "$(dirname "$0")/lib.sh"

root="$(cd "$(dirname "$0")/.." && pwd)"

output="$(python3 "$root/tests/test_xui_chain.py" 2>&1)"
status=$?
assert_status "xui chain unit tests" "$status" "0"
assert_contains "unit test summary" "$output" "OK"

output="$(python3 "$root/tests/test_chain_workflow.py" 2>&1)"
status=$?
assert_status "offline HTTP workflow tests" "$status" "0"
assert_contains "workflow test summary" "$output" "OK"

ref="$root/references/chain-egress.md"
[ -f "$ref" ] || _fail "missing chain-egress reference"
TESTS_RUN=$((TESTS_RUN+1))
if [ -f "$ref" ]; then
  content="$(cat "$ref")"
  assert_contains "forced restart gate" "$content" "force restart"
  assert_contains "runtime readback gate" "$content" "runtime config"
  assert_contains "end-to-end gate" "$content" "end-to-end"
fi

finish
