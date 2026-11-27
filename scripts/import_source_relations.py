#!/usr/bin/env python3
"""Import pinned donor and open relationship tables as nonpublishable candidates."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

import yaml

KANJIUM_COMMIT = "9ebca4589565c696e7c39e089e2e928ad65f678c"
KANJIUM_HASHES = {
    "phonetics.txt": "a98e4ccec7bc379de9e035f0463ab481f05669850f9c39ff79a0f3b0fb8a18df",
    "kanjidict.txt": "78afcdee20b3291268ef1a85595b2e33c415547beb98b02413097ac759886419",
    "elements.txt": "bc8efa460a03a3d022771c71dd70a09b6b9e29cb034f8c3047ff3a1e5a6995e9",
    "radicals.txt": "f1b4cb8d63d5eda1ff3cf45a3f9ee2f2f4069c1d8cd9fed29ebd699bc6057250",
    "radicals_variants.txt": "6cd63cad7111150768dff9ccccbb2315a091ce79270f681d28f9042928e03740",
}
KANJIUM_SUPPORT_HASHES = {
    "README.md": "2ca73c9cfbe45f9e49db5ab80d514686a34dbcecde0b95040468c0da8ecde94f",
    "0_README.txt": "5d418ca98a4b6b178955a6578949e79f337bc8d9c97b9075bd7317c7512a8439",
}
KANJI_DB_COMMIT = "a0ca332b153a7538d1f8fd93d515dea4088e87f6"
KANJI_DB_HASHES = {
    "antonyms.tsv": "a399a2dbc5aa05ecf8876549cf0685bb6ce70561a5be7431cd45a70b6b8499ff",
    "phonetic-series.tsv": "74ba093c2824cca3d9b7e6e329f925c6d8f7026179453a33a96dcc614e3f5056",
    "similar-kanji.tsv": "50dfff2c178e6ca2195e48e3c997007910c256c09f97b6ba24574be0f468e3f9",
    "kunyomi-groups.tsv": "fffaa4679075159be74de8b39f483d01041d74c6d442b40366430ec697ecdec2",
    "homophone-groups.tsv": "2a36905c67faf8a655ea4ced07836f86d1bced244f89b9fa5ffc82466e51567d",
    "unlisted-variants.tsv": "4e6ead6676454172fc5743cc553e12a3a3de93cb47df8c5e5eda3eb75b39f87e",
}
DONOR_REVISION = "1f6357d491bdf2b81e9f87faaa45ca403ac25576"
DONOR_HASH = "5c07ece2a5ebc9736e0cea529497ee0185c33fa5864b43de7164b2d07faff525"
KANJIALIVE_COMMIT = "e1e24d39fc43e839948a8c7e99743b0994dedad5"
KANJIALIVE_ARCHIVE_HASH = "a36eb28c2a79fdc37f86fbc572173f62bab1dc82305bc46563331aff59fababa"
KANJIALIVE_ASSETS = {
    "山": ("radical-animations/yama0.svg", "ca59c5f464594230c4915292efefd04d9a112d85ca52d93d9af7ea136af68759", "Mountain"),
    "木": ("radical-animations/ki0.svg", "8fe35d6ae5e22dd9cb23390ac949c73682cfaced09002b6ca4510cb89f2863b8", "Tree / wood"),
    "貝": ("radical-animations/kai0.svg", "2339bae6421aadb818a1670c11f27ec57ab71fdfcfbdefb9b9a8db641207d598", "Shell"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(path: Path) -> str:
    return sha(path.read_bytes())


def yaml_bytes(doc: object) -> bytes:
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=110, explicit_start=True).encode("utf-8")


def source(identifier: str, author: str, project: str, url: str, license_id: str, version: str,
           license_url: str, scope: str, attribution: str, modifications: str, language: str,
           revision: str, acquisition: str, upstream: list[str], source_hash: str | None = None) -> dict:
    row = {"id": identifier, "author": author, "project": project, "url": url, "license": license_id,
           "licenseVersion": version, "licenseEvidenceURL": license_url, "scope": scope,
           "attribution": attribution, "modifications": modifications, "sourceLanguage": language,
           "upstream": upstream, "revision": revision, "acquisitionMethod": acquisition,
           "retrievedAt": "2026-11-27T07:57:00Z"}
    if source_hash:
        row["sha256"] = source_hash
    return row


def reference(identifier: str, source_id: str, url: str, external_id: str, locator: str,
              revision: str, snapshot_hash: str, supports: list[str]) -> dict:
    return {"id": identifier, "source": source_id, "url": url, "externalId": external_id,
            "locator": locator, "revision": revision, "snapshotHash": snapshot_hash,
            "retrievedAt": "2026-11-27T07:57:00Z", "supports": supports}


def candidate(kind: str, subject: dict, payload: dict, source_id: str, revision: str,
              reference_id: str, selector: str, *, status: str = "source-candidate") -> dict:
    payload_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    source_text = f"{kind}\0{reference_id}\0{selector}\0".encode() + payload_bytes
    return {"id": f"cand-{hashlib.sha256(source_text).hexdigest()[:24]}", "kind": kind, "subject": subject,
            "payload": payload, "source": source_id, "sourceRevision": revision, "reference": reference_id,
            "selector": selector, "sourceStatus": status, "japaneseApplicability": "unreviewed",
            "reviewState": "pending-independent-review", "publishable": False}


def add_registry(root: Path, source_rows: list[dict], ref_rows: list[dict]) -> None:
    path = root / "sources/registry.yaml"
    current = yaml.safe_load(path.read_text(encoding="utf-8"))
    smap = {row["id"]: row for row in current["sources"]}
    rmap = {row["id"]: row for row in current["references"]}
    for row in source_rows:
        if row["id"] in smap and smap[row["id"]] != row:
            raise SystemExit(f"source conflict {row['id']}")
        smap[row["id"]] = row
    for row in ref_rows:
        if row["id"] in rmap and rmap[row["id"]] != row:
            raise SystemExit(f"reference conflict {row['id']}")
        rmap[row["id"]] = row
    result = {"version": 1, "sources": list(smap.values()), "references": list(rmap.values())}
    if path.is_symlink():
        raise SystemExit("refusing symlink registry")
    path.write_bytes(yaml_bytes(result))


def read_tsv(path: Path, *, fieldnames: list[str] | None = None, header: bool = True) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        if header:
            return list(csv.DictReader(stream, delimiter="\t"))
        return list(csv.DictReader(stream, fieldnames=fieldnames, delimiter="\t"))


def flatten_donor(doc: dict) -> list[tuple[str, str, object]]:
    rows: list[tuple[str, str, object]] = []
    for char, value in doc["meaningLabels"].items():
        rows.append(("global-meaning-label", char, value))
    for category in ("occurrenceReviews", "wholeCharacterLessons", "historyLessons", "records", "ordinaryExamples",
                     "historyPresentation", "parentMappings", "meaningLabelReviews"):
        for char, value in doc.get(category, {}).items():
            if isinstance(value, list):
                for ordinal, item in enumerate(value, start=1):
                    rows.append((category, f"{char}/{ordinal}", item))
            else:
                rows.append((category, char, value))
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--donor-reviewed", type=Path, required=True)
    parser.add_argument("--kanjium-dir", type=Path, required=True)
    parser.add_argument("--kanji-db-dir", type=Path, required=True)
    parser.add_argument("--kanji-alive-archive", type=Path, required=True)
    parser.add_argument("--historical-dir", type=Path, required=True)
    parser.add_argument("--update-generated", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    for path in (args.donor_reviewed, args.kanjium_dir, args.kanji_db_dir, args.kanji_alive_archive, args.historical_dir):
        if path.is_symlink() or not path.exists():
            raise SystemExit(f"source input absent or a symlink: {path}")
    donor_hash = digest(args.donor_reviewed)
    if donor_hash != DONOR_HASH:
        raise SystemExit(f"donor snapshot hash mismatch: expected {DONOR_HASH}; got {donor_hash}")
    if digest(args.kanji_alive_archive) != KANJIALIVE_ARCHIVE_HASH:
        raise SystemExit("Kanji Alive media archive hash mismatch")
    for name, expected in (KANJIUM_HASHES | KANJIUM_SUPPORT_HASHES).items():
        if digest(args.kanjium_dir / name) != expected:
            raise SystemExit(f"Kanjium pinned input hash mismatch: {name}")
    for name, expected in KANJI_DB_HASHES.items():
        if digest(args.kanji_db_dir / name) != expected:
            raise SystemExit(f"kanji-db.com pinned input hash mismatch: {name}")

    sources = [
        source("kanjium-data", "Kanjium contributors", "Kanjium data tables",
               f"https://github.com/mifunetoshiro/kanjium/tree/{KANJIUM_COMMIT}/data/source_files", "CC-BY-SA", "4.0",
               "https://github.com/mifunetoshiro/kanjium/blob/master/README.md",
               "Pinned data/source_files phonetic, component, radical and scoped compact-meaning fields only; no fonts, binaries, or general reading/gloss duplication",
               "Kanjium contributors; https://github.com/mifunetoshiro/kanjium", "Converted pinned TSV rows into typed candidates; no source meaning promotion",
               "ja", KANJIUM_COMMIT, "Pinned upstream Git revision and exact per-file SHA-256", ["KANJIDIC2", "KanjiVG", "JMdict" ]),
        source("kanji-db-data", "uball and contributors", "kanji-db.com synthesized data",
               f"https://github.com/uball/kanji-db-data/tree/{KANJI_DB_COMMIT}/data", "CC-BY-SA", "4.0",
               f"https://github.com/uball/kanji-db-data/blob/{KANJI_DB_COMMIT}/LICENSE",
               "Published relationship tables in data/ only; preserve stated upstream KANJIDIC2/JMdict/KanjiVG/IDS/Unihan lineage",
               "kanji-db.com data contributors; https://kanji-db.com/licenses", "Imported exact TSV rows as unreviewed relationship candidates; no independent corroboration inferred",
               "ja", KANJI_DB_COMMIT, "Pinned Git commit and exact per-file SHA-256", ["KANJIDIC2", "JMdict", "KanjiVG", "IDS", "Unihan"]),
        source("manabidictionaries-editorial-v26", "ManabiDictionaries KanjiExplanation contributors", "Manabi Kanji Explanation v26",
               "https://github.com/ManabiIO/ManabiDictionaries/tree/" + DONOR_REVISION + "/SourceData/KanjiExplanation",
               "CC-BY-SA", "4.0", "https://creativecommons.org/licenses/by-sa/4.0/",
               "reviewed.json v26 editorial claims and review metadata only; no application code or excluded third-party content",
               "ManabiDictionaries KanjiExplanation v26 contributors; source revision and file digest retained",
               "Preserved all typed reviewed.json entries as unpublishable candidates until a new review binds evidence and Japanese applicability",
               "ja", DONOR_REVISION, "Pinned selected donor snapshot; byte hash independently verified", ["Wiktionary", "Dong Chinese", "KanjiVG"], DONOR_HASH),
        source("commons-acc-sears", "Wikimedia Commons Ancient Chinese Characters contributors", "Individually licensed historical SVG transcriptions",
               "https://commons.wikimedia.org/wiki/Commons:Ancient_Chinese_characters_project", "LicenseRef-ACC-Public-Domain-with-Fallback", "1.0",
               "https://commons.wikimedia.org/wiki/Template:ACClicense",
               "Only the 17 exact creator-cleared historical SVGs listed in the preserved HistoricalForms notice and provenance; no blanket project grant",
               "Per-file uploader and source credits retained in asset manifest and Commons provenance", "Original source SVG bytes preserved unchanged",
               "zh", "commons-file-revisions-pinned-in-assets-yaml", "Per-file description revision, upload identity, hash, source grant and permission record retained", []),
        source("commons-wargaz-shan", "Wargaz", "山 oracle-script transcription",
               "https://commons.wikimedia.org/wiki/File:山-oracle.svg", "Public-Domain", "1.0",
               "https://commons.wikimedia.org/wiki/File:山-oracle.svg?oldid=318110029",
               "Single 山 oracle SVG by Wargaz under its own public-domain release; not included under Sears permission",
               "Wargaz via Wikimedia Commons", "Original source SVG bytes preserved unchanged", "zh",
               "Commons description revision 318110029", "Per-file page and binary hash retained", []),
        source("kanji-alive-radical-media", "Kanji Alive contributors", "Kanji Alive educational radical drawings",
               f"https://github.com/kanjialive/kanji-data-media/tree/{KANJIALIVE_COMMIT}/radical-animations", "CC-BY", "4.0",
               "https://creativecommons.org/licenses/by/4.0/",
               "Three selected original radical illustrations 山, 木 and 貝 only; no hints, unrelated drawings, animations or fonts",
               "Kanji Alive, https://kanjialive.com/credits/", "Extracted three exact SVG members from a pinned source archive; no geometric redrawing",
               "ja", KANJIALIVE_COMMIT, "Pinned archive SHA-256 and individual original member SHA-256", []),
    ]
    refs: list[dict] = []
    import_rows: list[dict] = []
    # Kanjium sources: source-native memberships, elements, and concise component senses.
    k_refs = {}
    for name, expected in KANJIUM_HASHES.items():
        ref_id = "kanjium-" + name.replace("_", "-").replace(".txt", "")
        k_refs[name] = ref_id
        url = f"https://raw.githubusercontent.com/mifunetoshiro/kanjium/{KANJIUM_COMMIT}/data/source_files/{name}"
        refs.append(reference(ref_id, "kanjium-data", url, name, "Exact UTF-8 TSV source rows; row ordinals are one-based",
                              KANJIUM_COMMIT, expected, ["Source-native Japanese component and phonetic candidate fields"]))
        dest = root / "data/imports/source-files/kanjium" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            raise SystemExit(f"refusing symlink: {dest}")
        if not dest.exists() or dest.read_bytes() != (args.kanjium_dir / name).read_bytes():
            dest.write_bytes((args.kanjium_dir / name).read_bytes())

    phonetics = (args.kanjium_dir / "phonetics.txt").read_text(encoding="utf-8-sig").splitlines()
    for line_no, line in enumerate(phonetics, start=1):
        parts = line.split("\t")
        if len(parts) != 4:
            raise SystemExit(f"Kanjium phonetics row {line_no} has unexpected columns")
        phonetic, reading, occurrence, relation_type = parts
        import_rows.append(candidate("kanjium-phonetic-family", {"type": "component", "literal": phonetic},
                                     {"component": phonetic, "readingCandidate": reading, "reportedMembershipCount": occurrence,
                                      "sourceType": relation_type}, "kanjium-data", KANJIUM_COMMIT,
                                     k_refs["phonetics.txt"], f"line={line_no}"))

    k_fields = "kanji radical radvar phonetic idc type reg_on reg_kun onyomi kunyomi nanori strokes grade jlpt kanken frequency meaning compact_meaning rtk1_3_old rtk1_3_new ko2001 ko2301 wrp_jkf wanikani".split()
    for line_no, row in enumerate(read_tsv(args.kanjium_dir / "kanjidict.txt", fieldnames=k_fields, header=False), start=1):
        char = row.get("kanji", "")
        if len(char) != 1:
            continue
        base = {"character": char, "radicalForm": row.get("radical", ""), "radicalVariant": row.get("radvar", ""),
                "phoneticComponent": row.get("phonetic", ""), "idc": row.get("idc", ""), "sourceType": row.get("type", "")}
        if row.get("phonetic"):
            import_rows.append(candidate("kanjium-phonetic-membership", {"type": "character", "literal": char},
                                         base, "kanjium-data", KANJIUM_COMMIT, k_refs["kanjidict.txt"], f"line={line_no}"))
        if row.get("compact_meaning"):
            import_rows.append(candidate("kanjium-compact-meaning", {"type": "character", "literal": char},
                                         {"character": char, "compactMeaning": row["compact_meaning"], "sourceType": row.get("type", "")},
                                         "kanjium-data", KANJIUM_COMMIT, k_refs["kanjidict.txt"], f"line={line_no}; field=compact_meaning"))
    e_fields = "kanji strokes grade idc elements extra_elements kanji_parts part_of compact_meaning".split()
    for line_no, row in enumerate(read_tsv(args.kanjium_dir / "elements.txt", fieldnames=e_fields, header=False), start=1):
        char = row.get("kanji", "")
        if len(char) != 1:
            continue
        import_rows.append(candidate("kanjium-component-structure", {"type": "character", "literal": char},
                                     {"character": char, "idc": row.get("idc", ""), "elements": row.get("elements", ""),
                                      "extraElements": row.get("extra_elements", ""), "componentParts": row.get("kanji_parts", ""),
                                      "partOf": row.get("part_of", "")}, "kanjium-data", KANJIUM_COMMIT,
                                     k_refs["elements.txt"], f"line={line_no}"))
    for name, fieldnames in (("radicals.txt", "radical radvar number strokes names meaning notes".split()),
                             ("radicals_variants.txt", "radvar radical number strokes names meaning notes".split())):
        for line_no, row in enumerate(read_tsv(args.kanjium_dir / name, fieldnames=fieldnames, header=False), start=1):
            radical = row.get("radical") or row.get("radvar") or ""
            if len(radical) != 1:
                continue
            import_rows.append(candidate("kanjium-radical-name", {"type": "component", "literal": radical},
                                         {k: v for k, v in row.items() if v}, "kanjium-data", KANJIUM_COMMIT,
                                         k_refs[name], f"line={line_no}"))

    # kanji-db.com explicitly synthesizes these tables; all rows remain candidates with lineage intact.
    kb_refs = {}
    for name, expected in KANJI_DB_HASHES.items():
        rid = "kanji-db-" + name.removesuffix(".tsv")
        kb_refs[name] = rid
        url = f"https://raw.githubusercontent.com/uball/kanji-db-data/{KANJI_DB_COMMIT}/data/{name}"
        refs.append(reference(rid, "kanji-db-data", url, name, "Exact UTF-8 TSV data rows; header retained by source snapshot",
                              KANJI_DB_COMMIT, expected, ["Synthesized relationship candidates; upstream lineage retained"]))
        dest = root / "data/imports/source-files/kanji-db" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            raise SystemExit(f"refusing symlink: {dest}")
        if not dest.exists() or dest.read_bytes() != (args.kanji_db_dir / name).read_bytes():
            dest.write_bytes((args.kanji_db_dir / name).read_bytes())
        with (args.kanji_db_dir / name).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t"))
        for line_no, row in enumerate(rows, start=2):
            payload = {k: v for k, v in row.items() if v is not None and v != ""}
            char = row.get("kanji") or row.get("component") or row.get("reading") or row.get("word") or ""
            subject = {"type": "relation-row", "key": char}
            import_rows.append(candidate("kanji-db-" + name.removesuffix(".tsv"), subject, payload,
                                         "kanji-db-data", KANJI_DB_COMMIT, rid, f"line={line_no}"))

    # Retain all reviewed.json v26 records as candidates; missing citations become specific intake work.
    donor_doc = json.loads(args.donor_reviewed.read_text(encoding="utf-8"))
    if donor_doc.get("version") != 26 or donor_doc.get("license") != "CC-BY-SA-4.0":
        raise SystemExit("unexpected donor reviewed.json version or declared license")
    donor_ref = "manabidictionaries-reviewed-v26"
    refs.append(reference(donor_ref, "manabidictionaries-editorial-v26",
                          f"https://raw.githubusercontent.com/ManabiIO/ManabiDictionaries/{DONOR_REVISION}/SourceData/KanjiExplanation/reviewed.json",
                          "reviewed.json", "version=26; imported category and exact key/ordinal selector",
                          DONOR_REVISION, DONOR_HASH, ["Donor attribution and exact legacy candidate content only; not independent factual corroboration"]))
    donor_items = flatten_donor(donor_doc)
    category_counts: dict[str, int] = {}
    for kind, key, payload in donor_items:
        category_counts[kind] = category_counts.get(kind, 0) + 1
        primary = key.split("/", 1)[0]
        subject = {"type": "legacy-item", "key": primary}
        import_rows.append(candidate("donor-v26-" + kind, subject, {"key": key, "value": payload},
                                     "manabidictionaries-editorial-v26", DONOR_REVISION, donor_ref,
                                     f"/{kind}/{key}"))
    occurrence_reviews = sum(len(v) for v in donor_doc["occurrenceReviews"].values())
    component_overrides = sum(len(v.get("components", [])) for v in donor_doc["records"].values())
    coverage = {"schemaVersion": 1, "source": "ManabiDictionaries KanjiExplanation reviewed.json v26",
                "sourceRevision": DONOR_REVISION, "sourceSHA256": DONOR_HASH, "sourceLicense": "CC-BY-SA-4.0",
                "categoriesOverlap": True, "counts": {"globalMeaningLabels": len(donor_doc["meaningLabels"]),
                "occurrenceReviewCharacters": len(donor_doc["occurrenceReviews"]), "occurrenceReviewRows": occurrence_reviews,
                "wholeCharacterLessons": sum(map(len, donor_doc["wholeCharacterLessons"].values())),
                "localMeaningLabelReviews": sum(map(len, donor_doc["meaningLabelReviews"].values())),
                "recordOverrides": len(donor_doc["records"]), "componentOverrides": component_overrides,
                "historyLessons": len(donor_doc["historyLessons"]), "ordinaryExamples": len(donor_doc["ordinaryExamples"]),
                "parentMappings": len(donor_doc.get("parentMappings", {})), "historyPresentationSettings": len(donor_doc.get("historyPresentation", {})),
                "candidateRowsPreserved": len(donor_items)},
                "disposition": "All reviewed.json fields preserved as nonpublishable imported candidates. Source-level prior review labels are retained only as provenance; new independent evidence, Japanese-applicability and editorial review are required before promotion.",
                "pendingWork": [
                    "See donor-global-label-evidence.json for term-specific evidence and decisions on all 129 global labels",
                    "See donor-passages.json for verified public revisions and passage selectors for lessons, occurrences and mappings",
                    "See donor-v26-reading-examples.yaml for exact JMdict and ruby bindings for 98 examples and the two withheld decisions",
                    "Parent mappings require exact source-to-KanjiVG group verification",
                ]}
    coverage["relationshipImports"] = {
        "Kanjium": {"revision": KANJIUM_COMMIT, "phoneticFamilyRows": len(phonetics),
                    "phoneticMembershipRows": sum(row["kind"] == "kanjium-phonetic-membership" for row in import_rows),
                    "compactMeaningRows": sum(row["kind"] == "kanjium-compact-meaning" for row in import_rows),
                    "componentStructureRows": sum(row["kind"] == "kanjium-component-structure" for row in import_rows),
                    "radicalNameRows": sum(row["kind"] == "kanjium-radical-name" for row in import_rows),
                    "sourceFiles": KANJIUM_HASHES},
        "kanji-db.com": {"revision": KANJI_DB_COMMIT,
                         "rowsByTable": {name: sum(row["kind"] == "kanji-db-" + name.removesuffix(".tsv") for row in import_rows)
                                         for name in KANJI_DB_HASHES},
                         "sourceFiles": KANJI_DB_HASHES,
                         "disposition": "All table rows retained as source-lineage candidates; no row promoted to a Japanese teaching cue."},
        "historicalAssets": {"commonsIndividuallyPinnedSVGs": 18, "kanjiAliveEducationalDrawings": 3,
                             "allAssetsPendingDistinctAssetReview": True}}

    # Copy the full 18-file historical asset selection and its provenance/permission notices.
    asset_rows: list[dict] = []
    provenance_path = args.historical_dir / "commons-assets-provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    if not isinstance(provenance, list) or len(provenance) != 18:
        raise SystemExit("historical Commons asset provenance must contain the exact 18 selected records")
    commons_notice = (args.historical_dir / "NOTICE.md").read_bytes()
    sears_permission = (args.historical_dir / "sears-permission.json").read_bytes()
    out_hist = root / "assets/historical-forms"
    out_hist.mkdir(parents=True, exist_ok=True)
    for item in provenance:
        name = item["title"].removeprefix("File:")
        src = args.historical_dir / name
        if not src.is_file() or src.is_symlink() or digest(src) != item["sha256"]:
            raise SystemExit(f"historical asset identity/hash mismatch: {name}")
        dest = out_hist / name
        dest.write_bytes(src.read_bytes())
        desc_hash = sha(item["descriptionWikitext"].encode("utf-8"))
        subject = name.split("-", 1)[0]
        ident = "commons-" + f"u{ord(subject):x}-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        page_id = ident + "-description"
        binary_id = ident + "-binary"
        page_url = "https://commons.wikimedia.org/w/index.php?title=" + __import__("urllib.parse", fromlist=["quote"]).quote(item["title"], safe="") + f"&oldid={item['descriptionRevisionID']}"
        refs.extend([
            reference(page_id, "commons-wargaz-shan" if name == "山-oracle.svg" else "commons-acc-sears", page_url,
                      item["title"], f"description revision={item['descriptionRevisionID']}; exact wikitext retained in Commons provenance",
                      str(item["descriptionRevisionID"]), desc_hash, ["Per-file descriptive identity and specific grant selector"]),
            reference(binary_id, "commons-wargaz-shan" if name == "山-oracle.svg" else "commons-acc-sears", item["sourceURL"],
                      item["title"], f"file upload={item['fileTimestamp']}; uploader={item['uploader']}; SHA-256={item['sha256']}",
                      item["fileTimestamp"], item["sha256"], ["Exact selected SVG media bytes"]),
        ])
        asset_rows.append({"id": ident, "kind": "historical-transcription", "subject": subject,
                           "path": f"assets/historical-forms/{name}", "sha256": item["sha256"],
                           "source": "commons-wargaz-shan" if name == "山-oracle.svg" else "commons-acc-sears",
                           "revision": str(item["descriptionRevisionID"]), "descriptionReference": page_id,
                           "mediaReference": binary_id, "license": "Public-Domain" if name == "山-oracle.svg" else "LicenseRef-ACC-Public-Domain-with-Fallback",
                           "licenseEvidenceURL": "https://commons.wikimedia.org/wiki/File:" + name + "?oldid=" + str(item["descriptionRevisionID"]),
                           "attribution": "Wargaz via Wikimedia Commons" if name == "山-oracle.svg" else item["uploader"] + "; Richard Sears transcription with per-file permission, see source-notices/HISTORICAL-FORMS-NOTICE.md",
                           "status": "candidate", "reviewState": "pending-distinct-asset-review", "scriptLabel": item["metadata"].get("ImageDescription", {}).get("value", ""),
                           "selector": f"pageRevision={item['descriptionRevisionID']}; upload={item['fileTimestamp']}; SHA-256={item['sha256']}",
                           "dateIsUploadDateOnly": True})
    (root / "source-notices/HISTORICAL-FORMS-NOTICE.md").write_bytes(commons_notice)
    (root / "source-notices/commons-assets-provenance.json").write_bytes(provenance_path.read_bytes())
    (root / "source-notices/sears-permission.json").write_bytes(sears_permission)

    # Preserve only three independently licensed Kanji Alive teaching drawings.
    ka_ref = "kanji-alive-radical-animations"
    refs.append(reference(ka_ref, "kanji-alive-radical-media",
                          f"https://raw.githubusercontent.com/kanjialive/kanji-data-media/{KANJIALIVE_COMMIT}/radical-animations/radical-animations.zip",
                          "radical-animations.zip", "exact archive SHA-256; selected original members and their individual SHA-256 values",
                          KANJIALIVE_COMMIT, KANJIALIVE_ARCHIVE_HASH, ["Original Kanji Alive illustration bytes and attribution"]
                          ))
    ka_out = root / "assets/educational-radicals"
    ka_out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.kanji_alive_archive) as archive:
        for subject, (member, expected, title) in KANJIALIVE_ASSETS.items():
            raw = archive.read(member)
            if sha(raw) != expected:
                raise SystemExit(f"Kanji Alive member SHA-256 mismatch: {member}")
            filename = subject + ".svg"
            dest = ka_out / filename
            dest.write_bytes(raw)
            asset_id = f"kanji-alive-drawing-u{ord(subject):x}"
            asset_rows.append({"id": asset_id, "kind": "educational-radical-illustration", "subject": subject,
                               "path": f"assets/educational-radicals/{filename}", "sha256": expected,
                               "source": "kanji-alive-radical-media", "revision": KANJIALIVE_COMMIT,
                               "descriptionReference": ka_ref, "mediaReference": ka_ref,
                               "selector": f"archive-member={member}; memberSHA256={expected}; title={title}", "license": "CC-BY",
                               "licenseEvidenceURL": "https://creativecommons.org/licenses/by/4.0/",
                               "attribution": "Kanji Alive; https://kanjialive.com/credits/", "status": "candidate",
                               "reviewState": "pending-distinct-asset-review", "scriptLabel": title,
                               "dateIsUploadDateOnly": False})
    (root / "source-notices/KANJI-ALIVE-ANIMATIONS-NOTICE.md").write_text(
        "# Kanji Alive educational drawings\n\nThree original illustrations (山, 木, 貝) are retained as modern teaching artwork under CC BY 4.0. "
        "They are not historical script forms. Attribution: Kanji Alive, https://kanjialive.com/credits/. "
        "Source archive commit `" + KANJIALIVE_COMMIT + "`; source archive hash is recorded in the asset manifest. "
        "Kanji Alive mnemonic hints, graphics and fonts outside these three selected originals are excluded.\n", encoding="utf-8")

    for name, dest in (("CC-BY-4.0.txt", root / "source-notices/KANJI-ALIVE-CC-BY-4.0.txt"),
                       ("CC-BY-SA-4.0.txt", root / "source-notices/KANJIUM-CC-BY-SA-4.0.txt")):
        # The exact Creative Commons legal texts are from the licensed donor notice bundle.
        donor_license = args.historical_dir.parent / "Licenses" / name
        if donor_license.exists():
            dest.write_bytes(donor_license.read_bytes())
    (root / "source-notices/KANJIUM-README.md").write_bytes((args.kanjium_dir / "README.md").read_bytes())
    (root / "source-notices/KANJIUM-SOURCE-COLUMNS.txt").write_bytes((args.kanjium_dir / "0_README.txt").read_bytes())
    kanji_db_docs = args.kanji_db_dir.parent / "kanji-db-data"
    (root / "source-notices/KANJI-DB-ATTRIBUTION.md").write_bytes((kanji_db_docs / "ATTRIBUTION.md").read_bytes())
    (root / "source-notices/KANJI-DB-DATA-LICENSE.txt").write_bytes((kanji_db_docs / "LICENSE").read_bytes())

    def jsonl(rows: list[dict]) -> bytes:
        return b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in rows)
    asset_manifest = root / "assets/assets.yaml"
    owned_sources = {"commons-acc-sears", "commons-wargaz-shan", "kanji-alive-radical-media"}
    if asset_manifest.is_file():
        from kanjidb.yamlio import load
        asset_rows.extend(row for row in load(asset_manifest)["items"] if row["source"] not in owned_sources)
    asset_doc = {"version": 1, "items": asset_rows}
    asset_bytes = (asset_manifest.read_bytes() if asset_manifest.is_file() and load(asset_manifest) == asset_doc
                   else yaml_bytes(asset_doc))
    outputs = {
        root / "data/imports/relationships.jsonl": jsonl([row for row in import_rows if row["source"] != "manabidictionaries-editorial-v26"]),
        root / "data/imports/donor-v26.jsonl": b"".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode() + b"\n" for row in import_rows if row["source"] == "manabidictionaries-editorial-v26"),
        root / "data/coverage/donor-v26.yaml": yaml_bytes(coverage),
        asset_manifest: asset_bytes,
    }
    registry_path = root / "sources/registry.yaml"
    if registry_path.is_symlink():
        raise SystemExit("refusing symlink source registry")
    add_registry(root, sources, refs)
    for path, content in outputs.items():
        if path.is_symlink():
            raise SystemExit(f"refusing symlink output: {path}")
        if path.exists() and path.read_bytes() != content and not args.update_generated:
            raise SystemExit(f"generated output differs: {path}; pass --update-generated")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    raw_donor = root / "data/imports/source-files/donor-v26/reviewed.json"
    raw_donor.parent.mkdir(parents=True, exist_ok=True)
    if raw_donor.is_symlink():
        raise SystemExit(f"refusing symlink: {raw_donor}")
    if raw_donor.exists() and digest(raw_donor) != DONOR_HASH:
        raise SystemExit("existing donor snapshot file differs from the pinned donor")
    raw_donor.write_bytes(args.donor_reviewed.read_bytes())
    print(f"Imported {len(import_rows)} source-backed candidate rows; donor v26 items={len(donor_items)}, history assets={len(asset_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
