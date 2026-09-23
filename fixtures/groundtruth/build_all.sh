#!/usr/bin/env bash
# Build the ground-truth fixture three ways on Linux/macOS (development mirror of build_all.ps1).
#   out/debug/     Debug + symbols
#   out/release/   Release + symbols
#   out/stripped/  Release, symbols stripped  ← the recovery input
# Binaries are CI artifacts, never committed (see .gitignore).
set -euo pipefail
cd "$(dirname "$0")"
JUCE_TAG="${JUCE_TAG:-8.0.9}"
if [ ! -f third_party/JUCE/CMakeLists.txt ]; then
  mkdir -p third_party
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --branch "$JUCE_TAG" https://github.com/juce-framework/JUCE third_party/JUCE
fi
python3 gen.py
JOBS="${JOBS:-$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 2)}"
build() { # name, build-type, strip
  local name=$1 type=$2 strip=$3
  cmake -S . -B "build/$name" -DCMAKE_BUILD_TYPE="$type" -DAB_STRIP="$strip" -DCMAKE_EXPORT_COMPILE_COMMANDS=ON >/dev/null
  cmake --build "build/$name" --target ABGroundTruth_VST3 -j "$JOBS"
  rm -rf "out/$name"; mkdir -p "out/$name"
  cp -R "build/$name/ABGroundTruth_artefacts/$type/VST3/ABGroundTruth.vst3" "out/$name/"
  echo "built out/$name/ABGroundTruth.vst3 ($type, strip=$strip)"
}
# AB_VARIANTS selects a subset (CI builds only "release stripped"); default is all three.
VARIANTS="${AB_VARIANTS:-debug release stripped}"
for v in $VARIANTS; do
  case "$v" in
    debug)    build debug Debug OFF ;;
    release)  build release Release OFF ;;
    stripped) build stripped Release ON ;;
    *) echo "unknown variant $v" >&2; exit 2 ;;
  esac
done
python3 - <<'PY'
import hashlib, json, pathlib
out = {}
for v in ("debug", "release", "stripped"):
    if not pathlib.Path(f"out/{v}").is_dir():
        continue
    for p in pathlib.Path(f"out/{v}").rglob("*"):
        if p.is_file() and p.suffix in (".so", ".vst3", ".dll", ".dylib") and p.stat().st_size > 32768:
            out[v] = {"path": str(p), "size": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
pathlib.Path("out/builds.json").write_text(json.dumps(out, indent=2) + "\n")
print(json.dumps(out, indent=2))
PY
