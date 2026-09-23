"""Dependency registry (EXECUTE_ADDENDUM_A §A1): every adopted library and tool behind a small
interface, with its pinned version, licence and hash, so ``ab-cli doctor`` and
``docs/DEPENDENCIES.md`` say the same thing and nothing is imported ad hoc.

Python libraries are optional at import time: a missing one degrades the feature that needs it
(reported, never faked). ``available()`` is the single place stages ask before using one.
"""

from __future__ import annotations

import importlib
import importlib.metadata as md
from dataclasses import dataclass
from typing import Any

#: name → (distribution, pinned version, licence, sha256 of the pinned wheel/sdist as downloaded, slot)
PINNED: dict[str, dict[str, str]] = {
    "lief": {"dist": "lief", "version": "1.0.0", "license": "Apache-2.0", "sha256": "96277e45d58de45a33249079dac43e50db1c96da162fbe1ad02fbaa82e3bd06f",
             "artifact": "lief-1.0.0-cp311-cp311-manylinux_2_28_x86_64.whl", "slot": "static inventory (PE/ELF/Mach-O/PDB) beside the frozen v2 parsePE"},
    "capstone": {"dist": "capstone", "version": "5.0.9", "license": "BSD-3-Clause", "sha256": "273fd8d747d2e35c88f91450be51a603ecfaafb00d96d9f315dcb8689c86193e",
                 "artifact": "capstone-5.0.9-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", "slot": "function fingerprints before Ghidra (A3)"},
    "tlsh": {"dist": "py-tlsh", "version": "5.0.0", "license": "Apache-2.0 / BSD-3-Clause", "sha256": "a21cb75eb49e9d9237c8c39d2fb310a5c976b3abc6c35c2e405e16c089abad1b",
             "artifact": "py_tlsh-5.0.0.tar.gz", "slot": "approximate similarity — a relatedness signal, never identity"},
    "yara": {"dist": "yara-python", "version": "4.5.4", "license": "BSD-3-Clause", "sha256": "1a1721b61ee4e625a143e8e5bf32fa6774797c06724c45067f3e8919a8e5f8f3",
             "artifact": "yara_python-4.5.4-cp311-cp311-manylinux_2_17_x86_64.manylinux2014_x86_64.whl", "slot": "candidate-family rules (A4); output is CANDIDATE_FAMILY only"},
    "numpy": {"dist": "numpy", "version": ">=1.26", "license": "BSD-3-Clause", "sha256": "", "artifact": "", "slot": "behaviour metrics and fits"},
    "jsonschema": {"dist": "jsonschema", "version": ">=4.20", "license": "MIT", "sha256": "", "artifact": "", "slot": "contract validation of every emitted JSON"},
}

#: External tools (not Python): licence and where the pin lives
TOOLS: dict[str, dict[str, str]] = {
    "ghidra": {"license": "Apache-2.0", "pin": "tools/manifest.json", "slot": "deep RE: RTTI, callgraph, decompile — automated, never replaced"},
    "jdk": {"license": "GPLv2+CE (Temurin)", "pin": "tools/manifest.json", "slot": "Ghidra runtime"},
    "vst3sdk": {"license": "MIT (hosting classes; see BLOCKERS B-002)", "pin": "native/vst3host/build_all.* (v3.7.9_build_61)", "slot": "vst3host + Steinberg validator"},
    "validator": {"license": "MIT (VST3 SDK sample)", "pin": "built from the pinned SDK", "slot": "second validation source in the RUNTIME stage"},
    "pluginval": {"license": "GPLv3 — external executable only, never linked", "pin": "tools/manifest.json", "slot": "BUILD stage validation"},
    "juce": {"license": "AGPLv3 / commercial (owner's licence)", "pin": "tools/manifest.json", "slot": "rebuild framework"},
    "sqlite": {"license": "public domain", "pin": "Python stdlib", "slot": "jobs.db and knowledge.db"},
}


@dataclass
class Dep:
    name: str
    available: bool
    version: str | None
    pinned: str
    license: str
    sha256: str
    slot: str
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def check(name: str) -> Dep:
    spec = PINNED[name]
    try:
        mod = importlib.import_module(name)
    except Exception as exc:  # noqa: BLE001 — a broken native wheel must not take the engine down
        return Dep(name, False, None, spec["version"], spec["license"], spec["sha256"], spec["slot"], f"not importable: {exc.__class__.__name__}")
    try:
        ver = md.version(spec["dist"])
    except md.PackageNotFoundError:
        ver = str(getattr(mod, "__version__", "?"))
    pinned_ok = spec["version"].startswith(">=") or ver.split("-")[0] == spec["version"]
    return Dep(name, True, ver, spec["version"], spec["license"], spec["sha256"], spec["slot"], "" if pinned_ok else f"version {ver} differs from the pin {spec['version']}")


def available(name: str) -> bool:
    return check(name).available


def all_deps() -> list[Dep]:
    return [check(n) for n in PINNED]


def doctor_rows() -> list[dict[str, str]]:
    rows = []
    for d in all_deps():
        verdict = "PASS" if d.available and not d.detail else ("WARNING" if d.available else "UNAVAILABLE")
        rows.append({"name": f"dep:{d.name}", "verdict": verdict,
                     "detail": f"{d.version or 'missing'} · pinned {d.pinned} · {d.license}" + (f" · sha256 {d.sha256[:12]}…" if d.sha256 else "") + (f" · {d.detail}" if d.detail else "")})
    return rows


__all__ = ["PINNED", "TOOLS", "Dep", "check", "available", "all_deps", "doctor_rows"]
