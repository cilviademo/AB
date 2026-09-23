"""Content-addressed object store: ``objects/<sha256>`` (SPEC §5, AB_BRIEF).

Artifacts and carved bytes are stored once by SHA-256; per-plugin evidence
folders reference objects; a single-project export *materializes* real,
independent files so no exported project depends on another plugin's folder.
Refcounts live in ``jobs.db``; a job's objects are released when it is deleted.
"""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

from ab_engine.jobs import db as jobs_db

CHUNK = 4 * 1024 * 1024


def sha256_file(path: Path) -> tuple[str, int]:
    """Streamed SHA-256 (never reads a corpus binary into memory)."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ObjectStore:
    def __init__(self, root: Path, conn: sqlite3.Connection) -> None:
        self.root = Path(root)
        self.conn = conn
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha256: str) -> Path:
        return self.root / sha256[:2] / sha256

    def has(self, sha256: str) -> bool:
        return self.path_for(sha256).is_file()

    def put_bytes(self, data: bytes) -> str:
        sha = sha256_bytes(data)
        target = self.path_for(sha)
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".partial")
            tmp.write_bytes(data)
            tmp.replace(target)
        jobs_db.object_ref(self.conn, sha, len(data), +1)
        return sha

    def put_file(self, src: Path) -> tuple[str, int]:
        """Copy a file in by streaming; the hash is computed once, on the way."""
        sha, size = sha256_file(src)
        target = self.path_for(sha)
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".partial")
            shutil.copyfile(src, tmp)
            tmp.replace(target)
        jobs_db.object_ref(self.conn, sha, size, +1)
        return sha, size

    def get_path(self, sha256: str) -> Path:
        p = self.path_for(sha256)
        if not p.is_file():
            raise FileNotFoundError(f"object {sha256} is not in the store")
        return p

    def get_bytes(self, sha256: str) -> bytes:
        return self.get_path(sha256).read_bytes()

    def release(self, sha256: str) -> None:
        """Drop one reference; delete the bytes when nothing references them."""
        size = self.path_for(sha256).stat().st_size if self.has(sha256) else 0
        refs = jobs_db.object_ref(self.conn, sha256, size, -1)
        if refs <= 0:
            try:
                self.path_for(sha256).unlink()
            except FileNotFoundError:
                pass
            jobs_db.forget_object(self.conn, sha256)

    def materialize(self, logical_tree: dict[str, str], target_dir: Path) -> list[Path]:
        """Write ``{relative/path: sha256}`` as real files under ``target_dir``."""
        written: list[Path] = []
        for rel, sha in sorted(logical_tree.items()):
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                raise ValueError(f"refusing to materialize outside the target: {rel}")
            dest = Path(target_dir) / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.get_path(sha), dest)
            written.append(dest)
        return written
