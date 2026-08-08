#!/usr/bin/env bash
# ==============================================================================
# Tier 7 - Mutation Testing Runner (Mutmut)
# Target: src/engine/
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$PROJECT_ROOT/.env" ]; then
  set -a
  source "$PROJECT_ROOT/.env"
  set +a
fi

MUTMUT_EXEC="${MUTMUT_CMD:-mutmut}"
if ! command -v "$MUTMUT_EXEC" >/dev/null 2>&1; then
  if command -v uv >/dev/null 2>&1; then
    MUTMUT_EXEC="uv run mutmut"
  elif command -v python3 >/dev/null 2>&1; then
    MUTMUT_EXEC="python3 -m mutmut"
  fi
fi

echo "🚀 Starting Mutation Testing via Mutmut..."
echo "This will deliberately inject bugs into the engine to see if tests fail."
echo "Note: This may take a few minutes depending on CPU."
echo "----------------------------------------------------------------------"

# Run the mutations
$MUTMUT_EXEC run

echo ""
echo "📊 Mutation testing complete! Summary of results:"
# Show summary in terminal
$MUTMUT_EXEC results

echo ""
echo "🌐 Generating interactive HTML report..."
$MUTMUT_EXEC browse

echo ""
echo "✅ Done! You can view the full report with: $MUTMUT_EXEC browse"
echo ""
echo "🛠️  DEBUGGING COMMANDS:"
echo " - To inspect a surviving mutant: $MUTMUT_EXEC show <ID>"
echo " - To apply a mutant to your code: $MUTMUT_EXEC apply <ID>"
