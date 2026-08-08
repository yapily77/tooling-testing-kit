#!/usr/bin/env bash
set -euo pipefail

# Run the 01_start GOLD E2E test against the live tmux infra (bazi-infra, :8445).
# Must be run with the server already up (see tests/01_gold_snapshots/00_infra/start.sh).
cd "$(dirname "$0")/../../.."

if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

PORT="${APP_PORT:-8445}"
PYTHON_EXEC="${PYTHON_CMD:-python3}"

$PYTHON_EXEC -c "import sys, json; sys.path.insert(0,'.'); import tests.01_gold_snapshots.run as R; R.SERVER_URL=f'http://127.0.0.1:${PORT}'; R.HEALTH_ENDPOINT=f'{R.SERVER_URL}/health'; print(json.dumps(R.run_test_folder('01_start'), indent=2, default=str))"
