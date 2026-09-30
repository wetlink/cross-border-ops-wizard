#!/usr/bin/env bash
# Install the cross-border-ops-wizard skill into every supported agent's skills dir.
#
# Supported agents (installed if their skills dir exists, or with --all to create):
#   Claude Code  ~/.claude/skills
#   Codex        ~/.codex/skills
#   WorkBuddy    ~/.workbuddy/skills
#   OpenClaw     ~/.openclaw/skills
#   shared       ~/.agents/skills
#
# Usage:
#   scripts/install.sh                 # install into agent dirs that already exist
#   scripts/install.sh --all           # also create dirs for every known agent
#   scripts/install.sh --dest DIR ...  # install into explicit skills dir(s)
#   scripts/install.sh --dry-run
set -euo pipefail

SKILL_NAME="cross-border-ops-wizard"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_SKILL_MD="$ROOT_DIR/skill/$SKILL_NAME/SKILL.md"

KNOWN_DESTS=(
  "$HOME/.claude/skills"
  "$HOME/.codex/skills"
  "$HOME/.workbuddy/skills"
  "$HOME/.openclaw/skills"
  "$HOME/.agents/skills"
)

CREATE_ALL=0
DRY_RUN=0
EXPLICIT_DESTS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all) CREATE_ALL=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --dest) shift; EXPLICIT_DESTS+=("$1") ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -f "$SRC_SKILL_MD" ] || { echo "[error] missing $SRC_SKILL_MD" >&2; exit 1; }

# Assemble a fresh, self-contained skill bundle (SKILL.md + references + scripts),
# mirroring validate_skill_package.py's build_package. Always built from source so
# it never ships a stale copy.
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/${SKILL_NAME}.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
BUNDLE="$STAGE/$SKILL_NAME"
mkdir -p "$BUNDLE"
cp "$SRC_SKILL_MD" "$BUNDLE/SKILL.md"
for sub in references scripts; do
  [ -d "$ROOT_DIR/$sub" ] || continue
  # exclude .DS_Store and packaged zips
  (cd "$ROOT_DIR" && find "$sub" -type f ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '*.pyo' ! -name '.DS_Store' ! -name '*.zip' -print0) \
    | while IFS= read -r -d '' f; do
        mkdir -p "$BUNDLE/$(dirname "$f")"
        cp "$ROOT_DIR/$f" "$BUNDLE/$f"
      done
done

# Optional validation (best-effort).
if command -v python3 >/dev/null 2>&1 && [ -f "$ROOT_DIR/scripts/validate_skill_package.py" ]; then
  (cd "$ROOT_DIR" && python3 scripts/validate_skill_package.py) >/dev/null \
    && echo "[ok] package validated" || echo "[warn] validation skipped/failed (continuing)"
fi

# Resolve destinations.
DESTS=()
if [ "${#EXPLICIT_DESTS[@]}" -gt 0 ]; then
  DESTS=("${EXPLICIT_DESTS[@]}")
else
  for d in "${KNOWN_DESTS[@]}"; do
    if [ "$CREATE_ALL" -eq 1 ] || [ -d "$d" ]; then
      DESTS+=("$d")
    fi
  done
fi

[ "${#DESTS[@]}" -gt 0 ] || { echo "[warn] no agent skills dir found; use --all or --dest DIR"; exit 0; }

for d in "${DESTS[@]}"; do
  target="$d/$SKILL_NAME"
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "[dry-run] would install -> $target"
    continue
  fi
  mkdir -p "$d"
  rm -rf "$target"
  cp -R "$BUNDLE" "$target"
  echo "[ok] installed -> $target"
done
