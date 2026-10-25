#!/bin/sh
# Run the next auto-bmad epic without a human: from a terminal, cron, launchd or CI.
# Usage: run-epic.sh <project dir> <epic-N | story N-M> [--fast|--normal|--deep]
# Needs .claude/auto-bmad-headless.json in the project (/auto-bmad:setup writes it).
set -eu
cd "$1"
target="${2:?epic-N or story N-M}"
level="${3:-}"
log=".auto-bmad/runs/$(date +%Y%m%d-%H%M%S).jsonl"
mkdir -p "$(dirname "$log")"
claude -p "/auto-bmad:auto-bmad $target $level" \
  --permission-mode acceptEdits --permission-prompts none \
  --settings .claude/auto-bmad-headless.json \
  --output-format stream-json --verbose > "$log"
echo "log: $log"
