#!/usr/bin/env bash
#
# run-registry-scan.sh — Run the registry clashes scanner in a tmux window.
#
# This script launches the resumable LLM scanner inside a detached tmux
# session named `registry-scanner` so it keeps running after you detach.
#
# Usage:
#   ./run-registry-scan.sh                Run the full scanner with LLM verification
#   ./run-registry-scan.sh --scripts      Run only the AST pass (fast)
#

set -uo pipefail

WORKSPACE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCANNER_SCRIPT="hygiene/scanners/find_registry_clashes.py"
TMUX_SESSION="${TMUX_SESSION_SCANNER:-registry-scanner}"

# Parse args
MODE="--verify"
if [ "${1:-}" = "--scripts" ]; then
  MODE="--scripts"
fi

ENV_FILE="$WORKSPACE_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

PYTHON_EXEC="${PYTHON_CMD:-python3}"
if command -v uv >/dev/null 2>&1; then
    PYTHON_EXEC="uv run python"
fi

command -v tmux >/dev/null 2>&1 || { echo "ERROR: 'tmux' not found on PATH" >&2; exit 1; }

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Launching registry scanner in tmux session '$TMUX_SESSION' (cwd=$WORKSPACE_ROOT)"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Detach anytime with Ctrl-B then D. Re-run this script to attach."

# Build the command that runs INSIDE the tmux window.
RUN_CMD="cd '$WORKSPACE_ROOT' && export PYTHONUNBUFFERED=1; "
if [ -f "$ENV_FILE" ]; then
    RUN_CMD+="set -a; . '$ENV_FILE'; set +a; "
fi
RUN_CMD+="$PYTHON_EXEC '$SCANNER_SCRIPT' $MODE"

# Kill any prior session to avoid duplicate/colliding runs, then launch fresh.
tmux kill-session -t "$TMUX_SESSION" 2>/dev/null || true
tmux new-session -d -s "$TMUX_SESSION"
tmux send-keys -t "$TMUX_SESSION" "$RUN_CMD" Enter

# Attach so you watch it live ("send keys to activate").
exec tmux attach -t "$TMUX_SESSION"
