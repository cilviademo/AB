#!/usr/bin/env bash
# Build the unseen fixture (ADDENDUM B8 test 1). Default: only the stripped recovery input (AB_VARIANTS=stripped).
set -euo pipefail
cd "$(dirname "$0")"
JUCE_DIR="${JUCE_DIR:-$(cd .. && pwd)/groundtruth/third_party/JUCE}"
python3 gen.py
JOBS="${JOBS:-$(nproc 2>/dev/null || echo 2)}"
build() { local name=$1 type=$2 strip=$3
  cmake -S . -B "build/$name" -DJUCE_DIR="$JUCE_DIR" -DCMAKE_BUILD_TYPE="$type" -DAB_STRIP="$strip" >/dev/null
  cmake --build "build/$name" --target ABUnseen_VST3 -j "$JOBS"
  rm -rf "out/$name"; mkdir -p "out/$name"
  cp -R "build/$name/ABUnseen_artefacts/$type/VST3/ABUnseen.vst3" "out/$name/"
  echo "built out/$name/ABUnseen.vst3 ($type, strip=$strip)"; }
for v in ${AB_VARIANTS:-stripped}; do
  case "$v" in debug) build debug Debug OFF ;; release) build release Release OFF ;; stripped) build stripped Release ON ;; *) echo "unknown variant $v" >&2; exit 2 ;; esac
done
python3 - <<'PY'
import hashlib, json, pathlib
out = {}
for v in ("debug", "release", "stripped"):
    for p in pathlib.Path(f"out/{v}").rglob("*") if pathlib.Path(f"out/{v}").is_dir() else []:
        if p.is_file() and p.suffix in (".so", ".vst3", ".dll", ".dylib") and p.stat().st_size > 32768:
            out[v] = {"path": str(p), "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
pathlib.Path("out/builds.json").write_text(json.dumps(out, indent=2) + "\n"); print(json.dumps(out, indent=2))
PY
