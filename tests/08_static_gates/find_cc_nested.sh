#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

PYTHON_EXEC="${PYTHON_CMD:-python3}"
if command -v uv >/dev/null 2>&1; then
  PYTHON_EXEC="uv run python"
fi

RUFF_EXEC="${RUFF_CMD:-ruff}"
if ! command -v "$RUFF_EXEC" >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    RUFF_EXEC="uv run ruff"
  elif command -v python3 >/dev/null 2>&1; then
    RUFF_EXEC="python3 -m ruff"
  fi
fi

echo "=== CC Nested Scan (src/) ==="
echo ""
if [ -d "$PROJECT_ROOT/src" ]; then
  find "$PROJECT_ROOT/src" -name "*.py" -print0 | xargs -0 $PYTHON_EXEC "$SCRIPT_DIR/find_cc_nested.py" --min-cc 6
fi

echo ""
echo "=== Ruff Check Summary (src/) ==="
echo ""
cd "$PROJECT_ROOT"
if [ -d "src" ]; then
  $RUFF_EXEC check src/ 2>&1 | tail -5 || true
fi

echo ""
echo "=== CC>=6 Functions Detail ==="
echo ""
$PYTHON_EXEC -c "
from radon.complexity import cc_visit
from pathlib import Path

results = []
if Path('src').exists():
    for fpath in Path('src').rglob('*.py'):
        try:
            source = fpath.read_text(encoding='utf-8', errors='ignore')
            blocks = cc_visit(source)
            for b in blocks:
                if b.complexity >= 6:
                    results.append((b.complexity, str(fpath), b.name, b.lineno))
        except:
            pass

results.sort(reverse=True)
for cc, fpath, name, lineno in results:
    print(f'  CC {cc:3d}  {name:<40s}  {fpath}:{lineno}')
print(f'\nTotal CC>=6 functions: {len(results)}')
" 2>&1
