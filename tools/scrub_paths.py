#!/usr/bin/env python3
"""
Path & String Sanitizer Script
Scubs hardcoded project names (e.g., 'my-repo') and absolute machine paths,
replacing them with configurable tokens or environment variables.
"""

import os
import sys
import re

DEFAULT_LEGACY = "my-repo"
DEFAULT_TARGET = "my-repo"

EXCLUDE_DIRS = {".git", "node_modules", ".vite", "dist"}

def scrub_file(file_path, legacy, target):
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()

        if legacy in content:
            new_content = content.replace(legacy, target)
            new_content = re.sub(r'/[A-Za-z0-9_\-]+/projects/' + re.escape(target), './', new_content)
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"[SCRUBBED] {file_path}")
            return 1
    except Exception as e:
        print(f"[ERROR] Could not process {file_path}: {e}")
    return 0

def run_scrub(root_dir, legacy, target):
    scrubbed_count = 0
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for file in files:
            full_path = os.path.join(root, file)
            scrubbed_count += scrub_file(full_path, legacy, target)
    print(f"\nScrubbing Complete. Total files sanitized: {scrubbed_count}")

if __name__ == "__main__":
    legacy = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_LEGACY
    target = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TARGET
    print(f"Starting Repository Sanitization: '{legacy}' -> '{target}'")
    run_scrub(".", legacy, target)
