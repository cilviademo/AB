#!/usr/bin/env bash
# Developer setup on Linux/macOS: engine (editable), UI deps, Windows Rust target for cargo check.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -q -e "engine[dev]"
(cd app && npm ci --no-audit --no-fund)
rustup target add x86_64-pc-windows-msvc >/dev/null 2>&1 || true
echo "ok: run 'ab-cli --text doctor'"
