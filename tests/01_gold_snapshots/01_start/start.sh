#!/usr/bin/env bash
set -euo pipefail

# Run the 01_start GOLD E2E test against the live tmux infra (bazi-infra, :8445).
# Must be run with the server already up (see tests/01_gold_snapshots/00_infra/start.sh).
cd "$(dirname "$0")/../../.."

python3 -c 'import sys; sys.path.insert(0,"."); import tests.01_gold_snapshots.run as R; R.SERVER_URL="http://127.0.0.1:8445"; R.HEALTH_ENDPOINT=R.SERVER_URL+"/health"; import json; print(json.dumps(R.run_test_folder("01_start"), indent=2, default=str))'
