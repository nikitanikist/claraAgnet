#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Run scripts/install-mac.sh first.'
  exit 1
fi
exec .venv/bin/python -m clara serve
