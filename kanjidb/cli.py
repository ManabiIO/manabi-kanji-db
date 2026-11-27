from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from .database import build
from .validation import ValidationError, validate


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m kanjidb")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="validate YAML, sources, claims, and relationships")
    build_parser = sub.add_parser("build", help="build a deterministic SQLite snapshot")
    build_parser.add_argument("--output", type=Path, default=Path("dist/kanji.sqlite"))
    sub.add_parser("verify-reproducible", help="build twice in a clean temporary directory and compare hashes")
    audit = sub.add_parser("audit-citations", help="check pins and optionally retrieve exact public locators")
    audit.add_argument("--refresh", action="store_true", help="retrieve references and emit review queue")
    audit.add_argument("--output", type=Path, default=Path("dist/citation-review-queue.json"))
    audit.add_argument("--limit", type=int, default=100, help="maximum references to retrieve in this refresh batch")
    audit.add_argument("--offset", type=int, default=0, help="zero-based offset into the sorted reference list")
    package_parser = sub.add_parser("package", help="build the database and deterministic release archive")
    package_parser.add_argument("--output", type=Path, default=Path("dist/manabi-kanji-db-release.zip"))
    args = parser.parse_args()
    root = Path.cwd()
    try:
        if args.command == "validate":
            claims, sources, refs = validate(root)
            print(f"valid: {claims} claims, {sources} sources, {refs} exact references")
            return 0
        if args.command == "build":
            digest = build(root, args.output)
            print(f"built {args.output} sha256={digest}")
            return 0
        if args.command == "verify-reproducible":
            import os
            scratch = Path(tempfile.mkdtemp(prefix="kanjidb-repro-"))
            first, second = scratch / "first.sqlite", scratch / "second.sqlite"
            first_hash, second_hash = build(root, first), build(root, second)
            if first_hash != second_hash:
                raise ValidationError(f"builds differ: {first_hash} != {second_hash}")
            from .release import package_database
            first_release, second_release = scratch / "first.zip", scratch / "second.zip"
            first_release_hash = package_database(root, first, first_release)
            second_release_hash = package_database(root, second, second_release)
            if first_release_hash != second_release_hash:
                raise ValidationError(f"release archives differ: {first_release_hash} != {second_release_hash}")
            print(f"reproducible: database={first_hash}; release={first_release_hash}; artifacts={scratch}")
            return 0
        if args.command == "package":
            from .release import package
            digest = package(root, args.output)
            print(f"packaged {args.output} sha256={digest}")
            return 0
        if args.command == "audit-citations":
            from .audit import audit
            count = audit(root, args.output, refresh=args.refresh, limit=args.limit, offset=args.offset)
            print(f"citation audit: {count} references; queue={args.output}")
            return 0
    except (ValidationError, ValueError, OSError) as exc:
        parser.exit(1, f"error: {exc}\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
