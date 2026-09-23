#!/usr/bin/env bash
# Soak the engine suite the way the flake hunt did (ADDENDUM B7): N sequential runs, then runs under a CPU hog,
# then random-order runs (pytest-randomly). Every failure is named. Usage: tools/test_series.sh [N=3] [HOG=2] [RANDOM=2]
set -uo pipefail
cd "$(dirname "$0")/../engine"
N=${1:-3}; HOG=${2:-2}; RND=${3:-2}; fail=0
run() { local label=$1; shift; echo "== $label"; python -m pytest -q -p no:cacheprovider "$@" 2>&1 | grep -E "^FAILED|^ERROR|passed|failed|error" || true; }
for r in $(seq 1 "$N"); do run "sequential $r" -p no:randomly; done
if [ "$HOG" -gt 0 ]; then
  for i in $(seq 1 "$(nproc 2>/dev/null || echo 2)"); do python - <<'PY' &
import time; t=time.time()
while time.time()-t < 900: pass
PY
  done
  for r in $(seq 1 "$HOG"); do run "under CPU hog $r" -p no:randomly; done
  pkill -f "while time.time()-t < 900" 2>/dev/null || true
fi
if python -c "import pytest_randomly" 2>/dev/null; then for r in $(seq 1 "$RND"); do run "random order $r" -p randomly; done; else echo "random order: pip install pytest-randomly to enable"; fi
