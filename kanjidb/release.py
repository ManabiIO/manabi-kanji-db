from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .database import build


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _release_files(root: Path, database: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {"kanji.sqlite": database.read_bytes()}
    for name in ("LICENSE-CODE", "LICENSE-DATA", "README.md", "CONTRIBUTING.md"):
        path = root / name
        if path.is_file():
            files[name] = path.read_bytes()
    for base in ("schemas", "source-notices", "data/coverage", "assets"):
        directory = root / base
        if directory.exists():
            for path in sorted(directory.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    files[path.relative_to(root).as_posix()] = path.read_bytes()
    files["sources/registry.yaml"] = (root / "sources/registry.yaml").read_bytes()
    files["sources/reuse-scopes.json"] = (root / "sources/reuse-scopes.json").read_bytes()
    return files


def release_manifest(root: Path, database: Path) -> dict:
    with sqlite3.connect(database) as connection:
        database_schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        counts = {}
        for table in ("character", "component", "structure", "occurrence", "claim", "story", "source", "reference",
                      "written_form_pair", "joyo_appendix_reading", "joyo_appendix_jmdict_entry",
                      "radical_name", "imported_candidate", "candidate_relation", "asset", "intake"):
            counts[table] = connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        approved = connection.execute("SELECT count(*) FROM current_approved_claim").fetchone()[0]
        input_json = connection.execute("SELECT value FROM metadata WHERE key='inputManifest'").fetchone()[0]
    files = _release_files(root, database)
    return {"schemaVersion": 1, "databaseSchemaVersion": database_schema_version, "databaseSHA256": _sha(files["kanji.sqlite"]),
            "databaseBytes": len(files["kanji.sqlite"]), "approvedLocalizedClaims": approved,
            "counts": counts, "inputFiles": json.loads(input_json),
            "members": {name: {"bytes": len(data), "sha256": _sha(data)} for name, data in sorted(files.items())}}


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    import io
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo("manabi-kanji-db/" + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0
            archive.writestr(info, data)
    return buffer.getvalue()


def package_database(root: Path, database: Path, output: Path) -> str:
    files = _release_files(root, database)
    manifest = release_manifest(root, database)
    files["release-manifest.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    checksums = "".join(f"{_sha(data)}  {name}\n" for name, data in sorted(files.items()))
    files["checksums.sha256"] = checksums.encode("utf-8")
    packed = _zip_bytes(files)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError(f"refusing symlink package output: {output}")
    fd, temporary = tempfile.mkstemp(prefix=".kanji-release-", suffix=".zip", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(packed)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        raise
    return _sha(packed)


def package(root: Path, output: Path) -> str:
    with tempfile.TemporaryDirectory(prefix="kanjidb-package-") as directory:
        database = Path(directory) / "kanji.sqlite"
        build(root, database)
        return package_database(root, database, output)
