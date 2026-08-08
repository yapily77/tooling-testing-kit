#!/usr/bin/env bash
# Open-Source Developer Bootstrap Script

set -e

echo "=========================================================="
echo " Enterprise Quality & Sanitizer Toolkit - Bootstrap"
echo " Prepared for Accenture Technical Demonstration"
echo "=========================================================="

if [ ! -f .env ]; then
  echo "[1/3] Creating .env from .env.example..."
  cp .env.example .env
else
  echo "[1/3] Existing .env file found."
fi

echo "[2/3] Executing Path & String Scrubber..."
python3 tools/scrub_paths.py "baziforecaster" "my-repo"

echo "[3/3] Checking Node.js dependencies..."
npm install

echo "----------------------------------------------------------"
echo " Setup complete! Run 'npm run dev' to start the workspace."
echo "----------------------------------------------------------"
