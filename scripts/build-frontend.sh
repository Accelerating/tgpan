#!/bin/sh
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir/frontend"
# Dependency installation must also work from non-interactive terminals.
CI=true pnpm install --frozen-lockfile
pnpm build
mkdir -p "$project_dir/backend/static"
# Replace generated assets only; do not touch backend runtime data.
python3 - "$project_dir" <<'PY'
from pathlib import Path
import shutil
import sys
root = Path(sys.argv[1])
shutil.rmtree(root / 'backend/static')
shutil.copytree(root / 'frontend/dist', root / 'backend/static')
PY
