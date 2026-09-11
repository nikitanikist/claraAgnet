#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
CLARA_PYTHON="${CLARA_PYTHON:-python3}"
"$CLARA_PYTHON" -c 'import sys; assert sys.version_info >= (3,12), "Python 3.12 or newer is required"'
node -e 'const [a,b]=process.versions.node.split(".").map(Number); if(!(a===20&&b>=19||a===22&&b>=12||a>=23)) process.exit(1)'
if [ ! -x .venv/bin/python ]; then "$CLARA_PYTHON" -m venv .venv; fi
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
npm ci --ignore-scripts --no-fund --no-audit
.venv/bin/python -m pip check
.venv/bin/python -m clara doctor
printf '%s\n' 'Installed. Run ./Login-Clara.command, then ./Start-Clara.command.'
