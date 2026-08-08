#!/usr/bin/env bash
# Open-Source Developer Bootstrap Script

set -e

echo "=========================================================="
echo " Enterprise Quality & Sanitizer Toolkit - Bootstrap"
echo " Prepared for Accenture Technical Evaluation & Open Source"
echo "=========================================================="

if [ ! -f .env ]; then
  echo "[1/3] Creating .env from .env.example..."
  cp .env.example .env
else
  echo "[1/3] Existing .env file found."
fi

LEGACY_TOKEN="${1:-${TARGET_LEGACY_NAME:-legacy_project_name}}"
CLEAN_TOKEN="${2:-${TARGET_CLEAN_NAME:-my-repo}}"

echo "[2/3] Executing Path & String Scrubber ($LEGACY_TOKEN -> $CLEAN_TOKEN)..."
python3 tools/scrub_paths.py "$LEGACY_TOKEN" "$CLEAN_TOKEN"

echo "[3/3] Installing Python dependencies..."
pip install -e .

echo "----------------------------------------------------------"
echo " Setup complete! Run 'pytest'."
echo "----------------------------------------------------------"
