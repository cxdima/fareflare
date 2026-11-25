#!/bin/sh
# PostToolUse hook: after Claude Code edits or writes a Python file under src/, tests/ or
# scripts/, fix and format that one file with the project's Ruff, as `make format` would.
#
# Quiet and never blocking: what Ruff cannot fix, `make check` reports. Unused imports are
# left alone (F401 unfixable) because an edit often adds an import before the code that
# uses it. Does nothing when the project has no .venv, as in a git worktree.
python="$CLAUDE_PROJECT_DIR/.venv/bin/python"
[ -x "$python" ] || exit 0
file=$("$python" -c 'import json, sys; print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))') || exit 0
case "$file" in
  "$CLAUDE_PROJECT_DIR"/src/*.py | "$CLAUDE_PROJECT_DIR"/tests/*.py | "$CLAUDE_PROJECT_DIR"/scripts/*.py) ;;
  *) exit 0 ;;
esac
[ -f "$file" ] || exit 0
"$python" -m ruff check --fix --unfixable F401 --quiet "$file" > /dev/null 2>&1
"$python" -m ruff format --quiet "$file" > /dev/null 2>&1
exit 0
