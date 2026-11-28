#!/usr/bin/env python3
"""Verify Jōyō appendix spelling/reading links against a pinned JMdict_e gzip."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kanjidb.yamlio import load  # noqa: E402


def allowed_pairs(entry: ET.Element) -> set[tuple[str, str]]:
    spellings = {item.text or "" for item in entry.findall("./k_ele/keb")}
    pairs: set[tuple[str, str]] = set()
    for reading in entry.findall("./r_ele"):
        reb = reading.findtext("reb", default="")
        restrictions = {item.text or "" for item in reading.findall("re_restr")}
        no_kanji = reading.find("re_nokanji") is not None
        if no_kanji:
            continue
        applicable = restrictions if restrictions else spellings
        pairs.update((keb, reb) for keb in applicable if keb in spellings and reb)
    return pairs


def verify(jmdict_path: Path) -> tuple[int, int, int]:
    registry = load(ROOT / "sources" / "registry.yaml")
    source = next(row for row in registry["sources"] if row["id"] == "jmdict-e-2026-11-27")
    expected_sha = source.get("sha256")
    actual_sha = hashlib.sha256(jmdict_path.read_bytes()).hexdigest()
    if not expected_sha or actual_sha != expected_sha:
        raise ValueError(f"JMdict archive SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")

    wanted = load(ROOT / "data" / "joyo-appendix.yaml")["items"]
    entry_ids = {entry_id for row in wanted for entry_id in row["entryIDs"]}
    requested_pairs = {(row["spelling"], row["reading"]) for row in wanted}
    pairs_by_entry: dict[int, set[tuple[str, str]]] = {}
    entries_by_pair: dict[tuple[str, str], set[int]] = {pair: set() for pair in requested_pairs}
    with gzip.open(jmdict_path, "rb") as stream:
        for _, entry in ET.iterparse(stream, events=("end",)):
            if entry.tag != "entry":
                continue
            sequence = entry.findtext("ent_seq")
            if sequence is not None:
                entry_id = int(sequence)
                pairs = allowed_pairs(entry)
                if entry_id in entry_ids:
                    pairs_by_entry[entry_id] = pairs
                for pair in pairs & requested_pairs:
                    entries_by_pair[pair].add(entry_id)
            entry.clear()

    missing_ids = entry_ids - pairs_by_entry.keys()
    if missing_ids:
        raise ValueError(f"JMdict entry IDs not found: {sorted(missing_ids)}")
    errors = []
    for row in wanted:
        pair = row["spelling"], row["reading"]
        actual_ids = entries_by_pair[pair]
        if actual_ids != set(row["entryIDs"]):
            errors.append(
                f"{row['id']}: expected all JMdict entry IDs {sorted(actual_ids)} for {pair!r}; "
                f"canonical data records {sorted(row['entryIDs'])}"
            )
        for entry_id in row["entryIDs"]:
            if pair not in pairs_by_entry[entry_id]:
                errors.append(f"{row['id']}: {pair!r} is not an allowed pair in JMdict {entry_id}")
    if errors:
        raise ValueError("\n".join(errors))
    return len(wanted), len({(row["spelling"], row["reading"]) for row in wanted}), len(entry_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jmdict_gzip", type=Path, help="gzip archive matching the registry pin")
    args = parser.parse_args()
    rows, pairs, entries = verify(args.jmdict_gzip)
    print(f"verified: appendix_rows={rows}; exact_pairs={pairs}; JMdict_entries={entries}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
