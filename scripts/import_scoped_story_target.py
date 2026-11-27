#!/usr/bin/env python3
"""Import one narrowly scoped Kanji Alive meaning field for story target evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

import yaml

COMMIT = "966def0104648e83c3f95538c414c4862cba1bbf"
EXPECTED = "7b463876a0837bfb1f754a4e1bec43617b62f92b9839bbdf060d6ad0d8dbaf65"
TARGETS = {"記": "write down", "曜": "day of the week"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ka-data", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if root.is_symlink() or args.ka_data.is_symlink() or not args.ka_data.is_file():
        raise SystemExit("repository and pinned source input must be regular non-symlink paths")
    raw = args.ka_data.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED:
        raise SystemExit(f"ka_data.csv hash mismatch: expected {EXPECTED}, got {digest}")
    with args.ka_data.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    selected = {}
    for literal, meaning in TARGETS.items():
        matches = [row for row in rows if row.get("kanji") == literal]
        if len(matches) != 1 or matches[0].get("kmeaning") != meaning:
            raise SystemExit(f"pinned source field does not match the exact selected kanji/kmeaning value for {literal}")
        selected[literal] = meaning
    registry_path = root / "sources/registry.yaml"
    if registry_path.is_symlink():
        raise SystemExit("refusing symlink source registry")
    registry = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    source = {"id": "kanji-alive-scoped-kmeaning", "author": "Kanji Alive contributors", "project": "Kanji Alive language data",
              "url": f"https://github.com/kanjialive/kanji-data-media/tree/{COMMIT}/language-data",
              "license": "CC-BY", "licenseVersion": "4.0", "licenseEvidenceURL": "https://creativecommons.org/licenses/by/4.0/",
              "scope": "Only the kmeaning fields for the exact rows kanji=記 and kanji=曜 are imported. No readings, grades, examples, radical order, other meanings, hints, or media fields are used.",
              "attribution": "Kanji Alive, https://kanjialive.com/credits/", "modifications": "Selected the exact kanji=記 and kanji=曜 rows and their kmeaning fields by glyph identity; retained as scoped story-target evidence candidates.",
              "sourceLanguage": "en", "upstream": [], "revision": COMMIT,
              "acquisitionMethod": "Pinned raw CSV SHA-256 checked; only one exact field selected", "retrievedAt": "2026-11-27T07:57:00Z",
              "sha256": EXPECTED}
    reference = {"id": "kanji-alive-meaning-u8a18", "source": source["id"],
                 "url": f"https://raw.githubusercontent.com/kanjialive/kanji-data-media/{COMMIT}/language-data/ka_data.csv",
                 "externalId": "language-data/ka_data.csv", "locator": "CSV rows selected by exact kanji=記 and kanji=曜; field=kmeaning",
                 "revision": COMMIT, "snapshotHash": EXPECTED, "retrievedAt": "2026-11-27T07:57:00Z",
                 "supports": ["Exact selected English meaning fields for Japanese characters 記 and 曜"]}
    sources = {row["id"]: row for row in registry["sources"]}
    refs = {row["id"]: row for row in registry["references"]}
    if source["id"] in sources and any(sources[source["id"]].get(key) != source[key]
                                       for key in ("revision", "sha256", "license", "url")):
        raise SystemExit("Kanji Alive scoped source identity conflict")
    if reference["id"] in refs and any(refs[reference["id"]].get(key) != reference[key]
                                        for key in ("revision", "snapshotHash", "url")):
        raise SystemExit("Kanji Alive scoped reference identity conflict")
    sources[source["id"]] = source
    refs[reference["id"]] = reference
    registry_bytes = yaml.safe_dump({"version": 1, "sources": list(sources.values()), "references": list(refs.values())},
                                    allow_unicode=True, sort_keys=False, width=110, explicit_start=True).encode()
    lines = []
    for literal, meaning in selected.items():
        row = {"id": f"cand-kanji-alive-kmeaning-u{ord(literal):x}", "kind": "kanji-alive-scoped-target-meaning",
               "subject": {"type": "character", "literal": literal}, "payload": {"kanji": literal, "kmeaning": meaning},
               "source": source["id"], "sourceRevision": COMMIT, "reference": reference["id"],
               "selector": f"ka_data.csv[kanji='{literal}']/kmeaning", "sourceStatus": "source-candidate",
               "japaneseApplicability": "unreviewed", "reviewState": "pending-independent-review", "publishable": False}
        lines.append(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    content = ("\n".join(lines) + "\n").encode()
    output = root / "data/imports/kanji-alive-meaning.jsonl"
    notice = root / "source-notices/KANJI-ALIVE-KANJI-MEANING-NOTICE.md"
    if output.is_symlink() or notice.is_symlink():
        raise SystemExit("refusing symlink generated output")
    registry_path.write_bytes(registry_bytes)
    output.write_bytes(content)
    notice.write_text("# Kanji Alive scoped target meanings\n\nOnly the exact `kmeaning` fields for 記 and 曜 are included as story-target evidence candidates under CC BY 4.0. No readings, grades, examples, radical indices, other meanings, hints or media fields were copied. The selected source file is pinned by SHA-256 in `sources/registry.yaml`. Attribution: Kanji Alive, https://kanjialive.com/credits/.\n", encoding="utf-8")
    print(f"Imported {len(selected)} scoped candidate fields: " + ", ".join(f"{glyph}={meaning}" for glyph, meaning in selected.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
