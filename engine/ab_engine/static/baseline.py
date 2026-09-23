"""``ab-cli diff-baseline`` (SPEC §13, EXECUTE 1.4 gate).

A fixture is a folder ``fixtures/static_v2/<name>/`` holding ``fixture.json``::

    {"binary": "<path relative to repo root>",        # or
     "generator": ["python3", "fixtures/synthetic/make_fixture.py", "<out>"],
     "attachments": [{"path": "...", "kind": "preset"}],
     "sha256": "<expected sha256 of the binary, or null>"}

and ``baseline/`` with the v2 contract files plus ``performance.json``.
``--init`` writes the baseline from a fresh run. A diff compares, for every
v2 contract file, the *evidence-bearing* payload after removing volatile
fields (timestamps, timings, tool strings), and then timing against the
baseline: ≤ 20 % variance passes, more is reported as a perf regression.
No new false positives, no reinterpreted state keys, no lost resources, no
evidence-status changes, no illegal paths — every one is a named row.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from ab_engine import tools as tools_mod
from ab_engine.workers.run import run_worker
from ab_engine.workspace import Workspace

COMPARED = (
    "00_manifest/recovery_summary.json", "01_evidence/rtti/classes.json", "01_evidence/paths/build_path_evidence.json",
    "01_evidence/resources/index.json", "01_evidence/resources/binarydata_map.json", "01_evidence/binary/dsp_constants.json",
    "03_architecture/serialized_keys.json", "03_architecture/classes.json", "03_architecture/parameters.json",
    "07_agent_handoff/reconstruction_index.json",
)
VOLATILE = {"generated", "tool", "stages_ms", "scan_ms", "ms", "elapsed_ms", "heap", "sha256_of_run"}
ILLEGAL = re.compile(r'[<>:"|?*\x00-\x1f]|(^|/)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|/|$)|[. ]$', re.I)


def repo_root() -> Path:
    r = tools_mod.repo_root()
    if r is None:
        raise RuntimeError("diff-baseline needs a source checkout (docs/SPEC.md + engine/)")
    return r


def fixtures_dir() -> Path:
    return repo_root() / "fixtures" / "static_v2"


def _strip(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip(v) for k, v in obj.items() if k not in VOLATILE}
    if isinstance(obj, list):
        return [_strip(v) for v in obj]
    return obj


def _resolve_binary(fx: dict[str, Any], tmp: Path) -> Path:
    root = repo_root()
    if fx.get("generator"):
        out = tmp / "fixture.bin"
        argv = [str(a).replace("<out>", str(out)) for a in fx["generator"]]
        subprocess.run(argv, cwd=root, check=True, capture_output=True)
        return out
    p = root / fx["binary"]
    if not p.is_file():
        raise FileNotFoundError(f"fixture binary {p} is not present (BLOCKERS B-001)")
    return p


def run_fixture(ws: Workspace, name: str, deep: bool = False) -> tuple[Path, dict[str, Any]]:
    """Run the static engine on a fixture into a temp dir; return (out_dir, static_result)."""
    fdir = fixtures_dir() / name
    fx = json.loads((fdir / "fixture.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp(prefix=f"ab-baseline-{name}-", dir=ws.tmp))
    binary = _resolve_binary(fx, tmp)
    if fx.get("sha256"):
        import hashlib  # noqa: PLC0415

        actual = hashlib.sha256(binary.read_bytes()).hexdigest()
        if actual != fx["sha256"]:
            raise RuntimeError(f"{name}: binary sha256 {actual} != fixture.json {fx['sha256']}")
    inputs = [{"path": fx.get("logical_path", binary.name), "fs_path": str(binary), "kind": "binary", "format": fx.get("format", "PE")}]
    for a in fx.get("attachments", []):
        inputs.append({"path": a["path"], "fs_path": str(repo_root() / a["fs_path"]), "kind": a["kind"], "format": "PE"})
    (tmp / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    node, cli = tools_mod.find_node(ws), tools_mod.find_static_engine_cli()
    if not node.present or not cli.present:
        raise RuntimeError("diff-baseline needs Node and app/static-engine/dist/cli.mjs (npm run build in app/)")
    argv = [node.path or "node", cli.path or "", "analyze", "--inputs", str(tmp / "inputs.json"), "--out", str(tmp / "out"), "--key", fx.get("key", name)]
    if deep:
        argv.append("--deep")
    res = run_worker("static-engine", argv, timeout=1800, log_dir=ws.logs / "baseline", cwd=tmp, keep_cwd=True, parse_json_stdout=True)
    if not res.ok:
        raise RuntimeError(f"{name}: static engine failed (exit {res.exit_code}); see {res.stderr_path}")
    result = json.loads((tmp / "out" / "static_result.json").read_text(encoding="utf-8"))
    return tmp / "out", result


def init_baseline(ws: Workspace, name: str) -> Path:
    out, result = run_fixture(ws, name)
    bdir = fixtures_dir() / name / "baseline"
    if bdir.exists():
        shutil.rmtree(bdir)
    bdir.mkdir(parents=True)
    for rel in COMPARED:
        src = out / rel
        if src.is_file():
            (bdir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, bdir / rel)
    (bdir / "performance.json").write_text(json.dumps({"instrumentation": result["instrumentation"], "summary": result["summary"]}, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(out.parent, ignore_errors=True)
    return bdir


def _payload(path: Path) -> Any:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return _strip(doc.get("data", doc))


def _diff(a: Any, b: Any, where: str, out: list[str], limit: int = 40) -> None:
    if len(out) >= limit:
        return
    if type(a) is not type(b):
        out.append(f"{where}: type {type(a).__name__} → {type(b).__name__}")
        return
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{where}.{k}: added")
            elif k not in b:
                out.append(f"{where}.{k}: removed")
            else:
                _diff(a[k], b[k], f"{where}.{k}", out, limit)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(f"{where}: length {len(a)} → {len(b)}")
        for i, (x, y) in enumerate(zip(a, b, strict=False)):
            _diff(x, y, f"{where}[{i}]", out, limit)
    elif a != b:
        out.append(f"{where}: {a!r} → {b!r}")


def diff_fixture(ws: Workspace, name: str) -> dict[str, Any]:
    bdir = fixtures_dir() / name / "baseline"
    if not bdir.is_dir():
        return {"fixture": name, "ok": False, "state": "NO_BASELINE", "rows": [{"check": "baseline", "ok": False, "detail": "run ab-cli diff-baseline --init " + name}]}
    out, result = run_fixture(ws, name)
    rows: list[dict[str, Any]] = []
    ok = True
    # 1. evidence payloads
    for rel in COMPARED:
        base, fresh = bdir / rel, out / rel
        if not base.is_file():
            continue
        if not fresh.is_file():
            rows.append({"check": rel, "ok": False, "detail": "missing from the fresh run"})
            ok = False
            continue
        diffs: list[str] = []
        _diff(_payload(base), _payload(fresh), "data", diffs)
        rows.append({"check": rel, "ok": not diffs, "detail": "identical" if not diffs else "; ".join(diffs[:8]) + (f" (+{len(diffs) - 8})" if len(diffs) > 8 else "")})
        ok = ok and not diffs
    # 2. named regressions (SPEC §13) from the summaries
    perf = json.loads((bdir / "performance.json").read_text(encoding="utf-8"))
    bs, fs = perf["summary"], result["summary"]
    named = [
        ("no new false positives", (fs.get("classes", {}).get("FALSE_POSITIVE", 0)) <= (bs.get("classes", {}).get("FALSE_POSITIVE", 0)) and fs.get("plugin_owned", 0) <= bs.get("plugin_owned", 0)),
        ("no state keys reinterpreted as parameters", fs.get("parameters", {}).get("verified") == bs.get("parameters", {}).get("verified")),
        ("no lost resources", fs.get("valid_resources", 0) >= bs.get("valid_resources", 0)),
        ("no evidence-status changes", fs.get("resources") == bs.get("resources") and fs.get("binarydata") == bs.get("binarydata")),
    ]
    for label, passed in named:
        rows.append({"check": label, "ok": bool(passed), "detail": "ok" if passed else f"baseline {json.dumps(bs.get('resources'))} fresh {json.dumps(fs.get('resources'))}"})
        ok = ok and bool(passed)
    # 3. illegal paths in the plan
    bad = [f["path"] for f in result.get("files", []) if ILLEGAL.search(f["path"])]
    rows.append({"check": "no illegal paths", "ok": not bad, "detail": "ok" if not bad else ", ".join(bad[:5])})
    ok = ok and not bad
    # 4. timing variance ≤ 20 %
    b_ms, f_ms = perf["instrumentation"]["elapsed_ms"], result["instrumentation"]["elapsed_ms"]
    variance = abs(f_ms - b_ms) / max(1, b_ms)
    perf_ok = variance <= 0.20 or abs(f_ms - b_ms) <= 50  # sub-50 ms differences are timer noise, not regressions
    rows.append({"check": "timing variance ≤ 20 %", "ok": perf_ok, "detail": f"baseline {b_ms} ms, fresh {f_ms} ms ({variance * 100:.0f} %)"})
    rows.append({"check": "completeness", "ok": True, "detail": result["instrumentation"]["completeness"]})
    shutil.rmtree(out.parent, ignore_errors=True)
    return {"fixture": name, "ok": ok, "perf_ok": perf_ok, "rows": rows}


def all_fixtures() -> list[str]:
    d = fixtures_dir()
    return sorted(p.name for p in d.iterdir() if (p / "fixture.json").is_file()) if d.is_dir() else []


from ab_engine.cli import subcommand  # noqa: E402


@subcommand("diff-baseline", "run the static engine on the regression fixtures and diff against fixtures/static_v2 baselines")
def _cli_diff(p):
    p.add_argument("fixtures", nargs="*", help="fixture names (default: all)")
    p.add_argument("--init", action="store_true", help="(re)write the baseline from a fresh run instead of diffing")

    def run(args, ws):
        names = args.fixtures or all_fixtures()
        if not names:
            sys.stdout.write(json.dumps({"ok": False, "detail": "no fixtures under fixtures/static_v2 (BLOCKERS B-001)"}) + "\n")
            return 1
        results = []
        rc = 0
        for n in names:
            try:
                if args.init:
                    results.append({"fixture": n, "ok": True, "state": "BASELINE_WRITTEN", "path": str(init_baseline(ws, n))})
                else:
                    r = diff_fixture(ws, n)
                    results.append(r)
                    rc = rc or (0 if r["ok"] else 1)
            except Exception as exc:  # noqa: BLE001
                results.append({"fixture": n, "ok": False, "state": "ERROR", "detail": str(exc)})
                rc = 1
        sys.stdout.write(json.dumps({"ok": rc == 0, "results": results}, indent=2) + "\n")
        if args.text:
            for r in results:
                sys.stderr.write(f"{'PASS' if r['ok'] else 'FAIL'}  {r['fixture']}\n")
                for row in r.get("rows", []):
                    sys.stderr.write(f"      {'ok  ' if row['ok'] else 'DIFF'} {row['check']}: {row['detail']}\n")
        return rc
    p.set_defaults(func=run)
