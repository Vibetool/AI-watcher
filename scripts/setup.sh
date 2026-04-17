#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
python3 -m pip install --user -r scripts/requirements.txt

echo "ONVIF Python dependencies installed for the current python3 interpreter."
echo "Use the same python3 executable for both installation and runtime commands."

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "Warning: ffmpeg is not installed. Snapshot capture from RTSP streams will not work until ffmpeg is available."
fi
