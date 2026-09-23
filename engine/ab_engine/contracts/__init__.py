"""Data contracts (SPEC §17, AB_BRIEF "Schema versioning").

Every structured file AB writes is an envelope::

    {"schema": "<name>", "schema_version": <int>, "tool": "<tool>",
     "generated": "<iso8601>", "data": <payload>}

Two families exist (DECISIONS D-004):

* ``recovery.*`` / version 2 — emitted by the frozen Static Recovery v2 port,
  byte-for-byte the v2 identity so baselines diff on them.
* ``artifactbench.*`` / version 1 — everything AB adds.

Schemas live beside this file as ``schemas/<schema>.schema.json`` and are
loaded by the TS engine and the Ghidra scripts too. Unknown major versions are
rejected; stale output is never reinterpreted.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from ab_engine import TOOL

SCHEMA_DIR = Path(__file__).parent / "schemas"

#: Current major version per schema family. A file whose major differs is rejected.
FAMILY_VERSIONS = {"recovery": 2, "artifactbench": 1}


class ContractError(ValueError):
    """The envelope or payload does not satisfy its contract."""


def envelope(schema: str, data: Any, *, tool: str = TOOL, version: int | None = None) -> dict:
    family = schema.split(".", 1)[0]
    if family not in FAMILY_VERSIONS:
        raise ContractError(f"unknown schema family {family!r} in {schema!r}")
    return {
        "schema": schema,
        "schema_version": FAMILY_VERSIONS[family] if version is None else version,
        "tool": tool,
        "generated": datetime.now(UTC).isoformat(),
        "data": data,
    }


@lru_cache(maxsize=None)
def load_schema(schema: str) -> dict | None:
    path = SCHEMA_DIR / f"{schema}.schema.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def check_envelope(doc: Any, *, expect: str | None = None) -> str:
    """Validate the envelope shape and major version; return the schema name."""
    if not isinstance(doc, dict):
        raise ContractError("a contract document must be a JSON object")
    for key in ("schema", "schema_version", "tool", "generated", "data"):
        if key not in doc:
            raise ContractError(f"envelope is missing {key!r}")
    schema = str(doc["schema"])
    if expect is not None and schema != expect:
        raise ContractError(f"expected schema {expect!r}, found {schema!r}")
    family = schema.split(".", 1)[0]
    if family not in FAMILY_VERSIONS:
        raise ContractError(f"unknown schema family {family!r}")
    version = doc["schema_version"]
    if not isinstance(version, int) or version != FAMILY_VERSIONS[family]:
        raise ContractError(
            f"{schema}: schema_version {version!r} is not supported "
            f"(this engine reads {family} v{FAMILY_VERSIONS[family]}); refusing to reinterpret"
        )
    return schema


def validate(doc: Any, *, expect: str | None = None, strict: bool = False) -> str:
    """Validate envelope + payload. ``strict`` fails when no payload schema exists."""
    schema = check_envelope(doc, expect=expect)
    payload_schema = load_schema(schema)
    if payload_schema is None:
        if strict:
            raise ContractError(f"no payload schema on disk for {schema}")
        return schema
    try:
        jsonschema.validate(doc["data"], payload_schema)
    except jsonschema.ValidationError as exc:
        raise ContractError(f"{schema}: {exc.message} at {'/'.join(str(p) for p in exc.absolute_path)}") from exc
    return schema


def write_json(path: Path, schema: str, data: Any, *, tool: str = TOOL) -> dict:
    """Wrap, validate and write. The only sanctioned way to emit a contract file."""
    doc = envelope(schema, data, tool=tool)
    validate(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".partial")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    return doc


def read_json(path: Path, *, expect: str | None = None) -> dict:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(doc, expect=expect)
    return doc


def known_schemas() -> list[str]:
    return sorted(p.name[: -len(".schema.json")] for p in SCHEMA_DIR.glob("*.schema.json"))
