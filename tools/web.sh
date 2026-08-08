#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${PROJECT_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

PYTHON_EXEC="${PYTHON_CMD:-python3}"
if command -v uv >/dev/null 2>&1; then
  PYTHONPATH="$PROJECT_ROOT" uv run python "$SCRIPT_DIR/web.py" "$@"
else
  PYTHONPATH="$PROJECT_ROOT" $PYTHON_EXEC "$SCRIPT_DIR/web.py" "$@"
fi
