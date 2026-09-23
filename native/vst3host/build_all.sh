#!/usr/bin/env bash
# Build vst3host on Linux/macOS. Clones the VST3 SDK (with submodules) on first run.
set -euo pipefail
cd "$(dirname "$0")"
SDK_TAG="${VST3_SDK_TAG:-v3.7.9_build_61}"
if [ ! -f third_party/vst3sdk/CMakeLists.txt ]; then
  mkdir -p third_party
  GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 --branch "$SDK_TAG" --recurse-submodules --shallow-submodules https://github.com/steinbergmedia/vst3sdk third_party/vst3sdk
fi
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build build --target vst3host -j "${JOBS:-$(nproc 2>/dev/null || echo 2)}"
./build/vst3host --version
