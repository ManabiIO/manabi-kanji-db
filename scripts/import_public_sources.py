#!/usr/bin/env python3
"""Import pinned public KanjiVG, KANJIDIC2 identity, and Kanji Alive radical data.

This command reads an explicit cache. Ordinary validation and release builds do
not retrieve source files. The importer writes only generated data inputs and
merges its own source records into the source registry.
"""

from __future__ import annotations

import argparse
import csv
import html
import gzip
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

KANJIVG_COMMIT = "d95a97627fd9fe5b2c8d06ca81e38149609c0c1e"
KANJIVG_RELEASE = "r20260714"
KANJIVG_ARCHIVE_SHA256 = "6a81219ef18a573b839695e81bd98c998ce81f3b4df5660f1421528c8e23f829"
KANJIDIC_SHA256 = "af6fafd267da4c807914420ca2393836e26efa66bf8fe911f6dc967a71283773"
KANJIALIVE_COMMIT = "966def0104648e83c3f95538c414c4862cba1bbf"
KANJIALIVE_RADICALS_SHA256 = "7c24ce865b286576d4239d5d9d3811c21c4f022afd764472cdde7894bb0df8b0"
KANJIALIVE_IDS_SHA256 = "ac1bf5273527e35fc15e1de34cc20c39af06416993d29d69432706a08848299b"
KANJIALIVE_LICENSE_SHA256 = "abc0a00defc51659a8b5d58d80aa9a6c443b5bbefed617dd989cf601a0f5f657"
WRITTEN_FORMS_SHA256 = "bc177eeb853fcfe53b42be9596b5903b521bbb1fa459952793f40ad462551161"
WRITTEN_FORMS_REVISION = "92671213"
RETRIEVED_AT = "2026-11-27T07:57:00Z"
KVG_NS = "{http://kanjivg.tagaini.net}"
XML_NS = "{http://www.w3.org/2000/svg}"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_yaml(value: object) -> bytes:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=110, explicit_start=True).encode("utf-8")


def stable_id(text: str) -> str:
    return re.sub(r"[^a-z0-9.-]+", "-", text.lower()).strip("-")


def codepoint(value: str) -> str:
    return f"U+{ord(value):04X}"


def require_hash(path: Path, expected: str) -> None:
    actual = digest(path)
    if actual != expected:
        raise SystemExit(f"{path}: SHA-256 mismatch, expected {expected}, received {actual}")


def source_record(source_id: str, *, author: str, project: str, url: str, license_name: str,
                  license_version: str, license_url: str, scope: str, attribution: str,
                  modifications: str, language: str, revision: str, source_hash: str | None,
                  acquisition: str, upstream: list[str]) -> dict:
    result = {
        "id": source_id, "author": author, "project": project, "url": url,
        "license": license_name, "licenseVersion": license_version,
        "licenseEvidenceURL": license_url, "scope": scope, "attribution": attribution,
        "modifications": modifications, "sourceLanguage": language, "upstream": upstream,
        "revision": revision, "acquisitionMethod": acquisition, "retrievedAt": RETRIEVED_AT,
    }
    if source_hash:
        result["sha256"] = source_hash
    return result


def reference(ref_id: str, source_id: str, url: str, external: str, locator: str,
              revision: str, file_hash: str, supports: list[str]) -> dict:
    return {"id": ref_id, "source": source_id, "url": url, "externalId": external,
            "locator": locator, "revision": revision, "snapshotHash": file_hash,
            "retrievedAt": RETRIEVED_AT, "supports": supports}


def read_kanjidic(path: Path) -> tuple[list[dict], str, str]:
    require_hash(path, KANJIDIC_SHA256)
    with gzip.open(path, "rb") as stream:
        root = ET.fromstring(stream.read())
    header = root.find("header")
    if header is None:
        raise SystemExit("KANJIDIC2 input has no header")
    version = header.findtext("file_version") or ""
    database_revision = header.findtext("database_version") or ""
    if version != "4" or database_revision != "2026-331":
        raise SystemExit(f"unexpected KANJIDIC2 pin: file={version}, database={database_revision}")
    characters: list[dict] = []
    for entry in root.findall("character"):
        literal = entry.findtext("literal")
        ucs = entry.find("codepoint/cp_value[@cp_type='ucs']")
        if not literal or len(literal) != 1 or ucs is None or ucs.text is None:
            continue
        if int(ucs.text, 16) != ord(literal):
            raise SystemExit(f"KANJIDIC2 literal/codepoint mismatch: {literal!r} / {ucs.text}")
        characters.append({"literal": literal, "codepoint": f"U+{int(ucs.text,16):04X}"})
    if len(characters) != len({row["literal"] for row in characters}):
        raise SystemExit("duplicate literal character in KANJIDIC2")
    joyo = 0
    for entry in root.findall("character"):
        grade = entry.findtext("misc/grade")
        if grade in {"1", "2", "3", "4", "5", "6", "8"}:
            joyo += 1
    if joyo != 2136:
        raise SystemExit(f"expected 2136 jōyō entries; received {joyo}")
    return characters, version, database_revision


def parse_svg(path: Path, literal: str) -> tuple[str, list[dict], list[dict]]:
    root = ET.parse(path).getroot()
    source_groups = [g for g in root.iter() if g.tag == XML_NS + "g" and g.get(KVG_NS + "element")]
    if not source_groups:
        raise ValueError(f"no element groups in {path}")
    root_group = source_groups[0]
    if root_group.get(KVG_NS + "element") != literal:
        raise ValueError(f"file/root character mismatch in {path}: {root_group.get(KVG_NS + 'element')!r}")
    structure_id = f"kv-{ord(literal):x}"
    components: dict[str, dict] = {}
    occurrences: list[dict] = []

    def walk(group: ET.Element, parent: str | None, ordinal: int) -> None:
        source_group_id = group.get("id", "")
        if not source_group_id.startswith("kvg:"):
            raise ValueError(f"missing KanjiVG group identity in {path}")
        form = group.get(KVG_NS + "element")
        if form and len(form) == 1:
            cid = f"cmp-u{ord(form):x}"
            kind = "encoded"
        else:
            suffix = source_group_id.removeprefix("kvg:")
            cid = f"cmp-kanjivg-{ord(literal):x}-{stable_id(suffix)}"
            kind = "group"
        components.setdefault(cid, {"id": cid, "form": form or "", "kind": kind,
                                    "source": "kanjivg-r20260714", "revision": KANJIVG_COMMIT})
        children = [child for child in list(group) if child.tag == XML_NS + "g"]
        stroke_ids = [child.get("id", "") for child in list(group)
                      if child.tag == XML_NS + "path" and child.get("id")]
        attrs = {name.removeprefix(KVG_NS): value for name, value in sorted(group.attrib.items())
                 if name.startswith(KVG_NS)}
        occ = {"id": source_group_id, "component": cid, "parent": parent, "ordinal": ordinal,
               "group": source_group_id, "strokeIDs": stroke_ids, "form": form or "",
               "sourceID": source_group_id, "attributes": attrs}
        occurrences.append(occ)
        for child_ordinal, child in enumerate(children):
            walk(child, source_group_id, child_ordinal)

    walk(root_group, None, 0)
    return structure_id, list(components.values()), occurrences


def read_radicals(radicals_path: Path, ids_path: Path) -> list[dict]:
    require_hash(radicals_path, KANJIALIVE_RADICALS_SHA256)
    require_hash(ids_path, KANJIALIVE_IDS_SHA256)
    with radicals_path.open(encoding="utf-8-sig", newline="") as stream:
        radical_rows = list(csv.DictReader(stream))
    with ids_path.open(encoding="utf-8-sig", newline="") as stream:
        id_rows = list(csv.DictReader(stream))
    if len(radical_rows) != 321 or len(id_rows) != 321:
        raise SystemExit(f"expected 321 radical rows in each CSV; got {len(radical_rows)} and {len(id_rows)}")
    result = []
    for rowno, (row, ids) in enumerate(zip(radical_rows, id_rows), start=2):
        radical = row.get("Radical", "")
        if not radical or len(radical) != 1 or ids.get("Radical") != radical:
            raise SystemExit(f"radical CSV identity mismatch at data row {rowno}")
        cp = ids.get("Codepoint", "")
        if cp and cp != codepoint(radical):
            raise SystemExit(f"radical literal/codepoint mismatch at data row {rowno}")
        variant_of = row.get("Variant-of", "")
        result.append({
            "id": f"ka-radical-{rowno-1:03d}", "literal": radical, "codepoint": codepoint(radical),
            "kangxiNumber": ids.get("Kangxi#") or None, "englishMeaning": row.get("Meaning") or None,
            "readingKana": row.get("Reading") or None, "readingRomanized": row.get("Reading-R") or None,
            "positionJapanese": row.get("Position-J") or None, "positionRomanized": row.get("Position-R") or None,
            "importance": row.get("Importance") or None, "origin": row.get("Origin") or None,
            "variantOf": variant_of or None, "variantOfReading": row.get("Variant-of-Reading") or None,
            "variantOfId": ids.get("Variant-of-ID") or None, "source": "kanji-alive-radicals-v2.4",
            "revision": KANJIALIVE_COMMIT, "reference": "kanji-alive-radicals-csv",
            "idsReference": "kanji-alive-radicals-ids-csv", "sourceRow": rowno,
            "sourceStatus": "candidate", "japaneseApplicability": "unreviewed",
        })
    return result


def read_written_forms(path: Path) -> list[dict]:
    require_hash(path, WRITTEN_FORMS_SHA256)
    text = path.read_text(encoding="utf-8")
    blocks = re.findall(r"\[\[(.*?)\]\]", text, flags=re.DOTALL)
    if not blocks:
        raise SystemExit("written-form Lua source has no literal data block")
    body = html.unescape(blocks[0])
    sections = [section for section in re.split(r"\n\s*\n", body.strip()) if section.strip()]
    categories = ["joyo-official-new-to-old", "joyo-unlisted-new-to-old", "joyo-extended", "jinmeiyo-official",
                  "jinmeiyo-unlisted", "hyogai-common", "hyogai-unlisted-old", "hyogai-extended",
                  "joyo-title-unsupported", "jinmeiyo-title-unsupported"]
    if len(sections) != len(categories):
        raise SystemExit(f"expected ten source categories, received {len(sections)}")
    rows: dict[tuple[str, str], dict] = {}
    occurrence_count = 0
    for part, section in enumerate(sections, start=1):
        for ordinal, token in enumerate(section.split(), start=1):
            if len(token) != 2:
                raise SystemExit(f"unexpected written-form token in part {part}, position {ordinal}: {token!r}")
            new_form, old_form = token[0], token[1]
            key = (new_form, old_form)
            row = rows.setdefault(key, {"id": f"wf-u{ord(new_form):x}-u{ord(old_form):x}", "newForm": new_form,
                                        "newCodepoint": codepoint(new_form), "oldForm": old_form,
                                        "oldCodepoint": codepoint(old_form), "categories": [], "source": "wiktionary-written-forms",
                                        "revision": WRITTEN_FORMS_REVISION, "reference": "wiktionary-written-forms-kyu",
                                        "sourceStatus": "candidate", "officialStatus": "unverified"})
            if categories[part-1] not in row["categories"]:
                row["categories"].append(categories[part-1])
            row["sourceOccurrences"] = row.get("sourceOccurrences", []) + [{"category": categories[part-1], "position": ordinal}]
            occurrence_count += 1
    if occurrence_count != 454 or len(rows) != 452:
        raise SystemExit(f"written-form count mismatch: occurrences={occurrence_count}, unique pairs={len(rows)}")
    return sorted(rows.values(), key=lambda row: (row["newCodepoint"], row["oldCodepoint"]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kanjivg-dir", type=Path, required=True, help="extracted KanjiVG release directory")
    parser.add_argument("--kanjivg-archive", type=Path, required=True, help="pinned .tar.gz used to verify the selected release")
    parser.add_argument("--kanjidic", type=Path, required=True, help="pinned KANJIDIC2 .xml.gz")
    parser.add_argument("--radicals-csv", type=Path, required=True)
    parser.add_argument("--radicals-ids-csv", type=Path, required=True)
    parser.add_argument("--kanjialive-license", type=Path, required=True)
    parser.add_argument("--written-forms", type=Path, required=True, help="pinned Wiktionary module bytes from the explicit cache")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--update-generated", action="store_true", help="replace differing importer-owned generated files")
    args = parser.parse_args()

    root = args.root.resolve(strict=True)
    if root.is_symlink():
        raise SystemExit("repository root cannot be a symlink")
    sys.path.insert(0, str(root))
    for path in (args.kanjivg_dir, args.kanjivg_archive, args.kanjidic, args.radicals_csv, args.radicals_ids_csv, args.kanjialive_license, args.written_forms):
        if not path.exists() or path.is_symlink():
            raise SystemExit(f"source input is absent or a symlink: {path}")
    require_hash(args.kanjivg_archive, KANJIVG_ARCHIVE_SHA256)
    require_hash(args.kanjialive_license, KANJIALIVE_LICENSE_SHA256)
    characters, file_version, db_version = read_kanjidic(args.kanjidic)
    char_by_literal = {row["literal"]: row for row in characters}
    svg_dir = args.kanjivg_dir / "kanji"
    if not svg_dir.is_dir():
        raise SystemExit(f"not a KanjiVG release directory: {args.kanjivg_dir}")

    source_rows = [
        source_record("kanjivg-r20260714", author="Ulrich Apel and KanjiVG contributors", project="KanjiVG",
                      url="https://github.com/KanjiVG/kanjivg/tree/r20260714", license_name="CC-BY-SA",
                      license_version="3.0", license_url="https://creativecommons.org/licenses/by-sa/3.0/",
                      scope="Japanese SVG stroke and group structure from kanji/*.svg; no other repository media",
                      attribution="KanjiVG, Ulrich Apel and contributors; https://kanjivg.tagaini.net/",
                      modifications="Parsed exact group IDs, element characters, group attributes and stroke IDs into relational occurrences",
                      language="ja", revision=f"{KANJIVG_RELEASE}@{KANJIVG_COMMIT}", source_hash=KANJIVG_ARCHIVE_SHA256,
                      acquisition="Verified GitHub release archive SHA-256", upstream=[]),
        source_record("kanjidic2-2026-331", author="Electronic Dictionary Research and Development Group and contributors",
                      project="KANJIDIC2", url="https://www.edrdg.org/kanjidic/kanjidic2.html", license_name="CC-BY-SA",
                      license_version="4.0", license_url="https://www.edrdg.org/edrdg/licence.html",
                      scope="Literal and Unicode codepoint identity plus exact selected-sense and Japanese-reading references; no general reading or meaning lists, grades, counts, or indexes copied",
                      attribution="EDRDG, KANJIDIC2; https://www.edrdg.org/edrdg/licence.html",
                      modifications="Selected literal and UCS codepoint for exact identity joins; selected sense and Japanese reading fields support individual teaching claims",
                      language="en", revision=f"file-{file_version}/database-{db_version}", source_hash=digest(args.kanjidic),
                      acquisition="Official EDRDG compressed XML; SHA-256 verified", upstream=[]),
        source_record("kanji-alive-radicals-v2.4", author="Kanji Alive contributors", project="Kanji Alive Japanese Radicals",
                      url="https://github.com/kanjialive/kanji-data-media/tree/" + KANJIALIVE_COMMIT,
                      license_name="CC-BY", license_version="4.0", license_url="https://creativecommons.org/licenses/by/4.0/",
                      scope="language-data/japanese-radicals.csv and japanese-radicals-ids.csv only; no hints, graphics, animations, or fonts",
                      attribution="Kanji Alive, https://kanjialive.com/credits/",
                      modifications="Rows kept as sourced candidates; IDs, codepoints, source row numbers, and variant links retained",
                      language="ja", revision=f"v2.4@{KANJIALIVE_COMMIT}", source_hash=None,
                      acquisition="Verified GitHub raw files at pinned commit", upstream=[]),
        source_record("wiktionary-written-forms", author="English Wiktionary contributors", project="Wiktionary Module:ja/data/kyu",
                      url="https://en.wiktionary.org/wiki/Module:ja/data/kyu?oldid=" + WRITTEN_FORMS_REVISION,
                      license_name="CC-BY-SA", license_version="4.0", license_url="https://en.wiktionary.org/wiki/Wiktionary:Copyrights",
                      scope="Exact new-form/old-form pairs and source category comments only; no claim of official adoption or chronology beyond the source category",
                      attribution="English Wiktionary contributors, Module:ja/data/kyu revision 92671213",
                      modifications="Numeric character entities decoded; duplicate pairs merged while retaining all source categories and positions; no Unicode normalization",
                      language="ja", revision="Module:ja/data/kyu@92671213", source_hash=WRITTEN_FORMS_SHA256,
                      acquisition="Donor retained exact UTF-8 module bytes; SHA-256 checked", upstream=[]),
    ]
    references = [
        reference("kanjidic2-identity-snapshot", "kanjidic2-2026-331", "https://www.edrdg.org/kanjidic/kanjidic2.xml.gz",
                  "KANJIDIC2 compressed XML", "header/file_version=4; header/database_version=2026-331; character/literal and codepoint/ucs",
                  "2026-331", digest(args.kanjidic), ["literal/codepoint identity", "exact selected sense reference only; no baseline text lists copied"]),
        reference("kanjidic2-selected-japanese-readings", "kanjidic2-2026-331", "https://www.edrdg.org/kanjidic/kanjidic2.xml.gz",
                  "KANJIDIC2 compressed XML", "header/file_version=4; header/database_version=2026-331; character/reading_meaning/rmgroup/reading with exact literal, reading type, and value selectors",
                  "2026-331", digest(args.kanjidic), ["Exact selected Japanese on and kun readings used as evidence for localized teaching claims"]),
        reference("kanji-alive-radicals-csv", "kanji-alive-radicals-v2.4",
                  f"https://raw.githubusercontent.com/kanjialive/kanji-data-media/{KANJIALIVE_COMMIT}/language-data/japanese-radicals.csv",
                  "language-data/japanese-radicals.csv", "CSV rows 2–322; radical, name, reading and variant columns",
                  KANJIALIVE_COMMIT, digest(args.radicals_csv), ["radical names and aliases as sourced candidate records"]),
        reference("kanji-alive-radicals-ids-csv", "kanji-alive-radicals-v2.4",
                  f"https://raw.githubusercontent.com/kanjialive/kanji-data-media/{KANJIALIVE_COMMIT}/language-data/japanese-radicals-ids.csv",
                  "language-data/japanese-radicals-ids.csv", "CSV rows 2–322; codepoint and variant identity columns",
                  KANJIALIVE_COMMIT, digest(args.radicals_ids_csv), ["radical codepoint identity and variant links"]),
        reference("wiktionary-written-forms-kyu", "wiktionary-written-forms",
                  "https://en.wiktionary.org/w/index.php?title=Module:ja/data/kyu&oldid=92671213&action=raw",
                  "Module:ja/data/kyu", "literal pairs grouped by the ten source category comments",
                  WRITTEN_FORMS_REVISION, WRITTEN_FORMS_SHA256, ["Japanese written-form pairs and source categories"]),
    ]
    char_rows = []
    component_map: dict[str, dict] = {}
    structures = []
    withheld = []
    for character in characters:
        literal = character["literal"]
        svg_path = svg_dir / f"{ord(literal):05x}.svg"
        if not svg_path.is_file():
            continue
        file_hash = digest(svg_path)
        ref_id = f"kanjivg-{ord(literal):x}"
        source_url = f"https://raw.githubusercontent.com/KanjiVG/kanjivg/{KANJIVG_COMMIT}/kanji/{svg_path.name}"
        try:
            structure_id, components, occurrences = parse_svg(svg_path, literal)
        except ValueError as exc:
            withheld.append({"id": f"source-identity-kanjivg-u{ord(literal):x}", "kind": "source-identity-mismatch",
                             "subject": {"type": "character", "literal": literal, "codepoint": codepoint(literal)},
                             "references": [ref_id], "reason": str(exc),
                             "nextAction": "human source editor to inspect the exact SVG path and decide whether to withhold or add an explicit crosswalk",
                             "disposition": "withheld", "publishable": False})
            references.append(reference(ref_id, "kanjivg-r20260714", source_url, svg_path.name,
                                        f"source SVG {svg_path.name}; root group retained for review", KANJIVG_COMMIT,
                                        file_hash, ["withheld structure identity evidence"]))
            continue
        references.append(reference(ref_id, "kanjivg-r20260714", source_url, svg_path.name,
                                    f"root element={literal}; groups and stroke ids preserved from exact SVG",
                                    KANJIVG_COMMIT, file_hash, ["Japanese visible structure and stroke/group selectors"]))
        char_rows.append({**character, "source": "kanjidic2-2026-331", "revision": f"file-{file_version}/database-{db_version}",
                          "reference": "kanjidic2-identity-snapshot",
                          "baseline": {"literal": character["literal"], "codepoint": character["codepoint"]}})
        for component in components:
            component["reference"] = ref_id
            prior = component_map.get(component["id"])
            if prior is None:
                component_map[component["id"]] = component
            elif component["kind"] == "encoded" and prior["form"] == component["form"]:
                continue
        structures.append({"id": structure_id, "literal": literal, "source": "kanjivg-r20260714",
                           "revision": KANJIVG_COMMIT, "selector": f"kanji/{svg_path.name}#kvg:{ord(literal):05x}",
                           "variant": "ja", "reference": ref_id, "occurrences": occurrences})
    # The official file's grade selection is checked separately and all 2,136 jōyō SVGs must be represented.
    with gzip.open(args.kanjidic, "rb") as stream:
        xml_root = ET.fromstring(stream.read())
    expected_joyo = {entry.findtext("literal") for entry in xml_root.findall("character")
                     if entry.findtext("misc/grade") in {"1", "2", "3", "4", "5", "6", "8"}}
    represented = {row["literal"] for row in char_rows}
    if not expected_joyo <= represented:
        missing = sorted(expected_joyo - represented)
        raise SystemExit(f"jōyō structures missing after identity checks ({len(missing)}): {''.join(missing[:30])}")
    radicals = read_radicals(args.radicals_csv, args.radicals_ids_csv)
    written_forms = read_written_forms(args.written_forms)
    for pair in written_forms:
        pair["newStructureAvailable"] = pair["newForm"] in represented
        pair["oldStructureAvailable"] = pair["oldForm"] in represented
    by_cp = {row["codepoint"]: row for row in characters}
    for row in radicals:
        row["baselineIdentityAvailable"] = row["codepoint"] in by_cp

    registry_path = root / "sources" / "registry.yaml"
    existing = {"version": 1, "sources": [], "references": []}
    if registry_path.exists():
        from kanjidb.yamlio import load
        existing = load(registry_path)
    source_map = {item["id"]: item for item in existing.get("sources", [])}
    for item in source_rows:
        if item["id"] in source_map and source_map[item["id"]] != item:
            if not args.update_generated:
                raise SystemExit(f"source registry conflict for {item['id']}")
        source_map[item["id"]] = item
    reference_map = {item["id"]: item for item in existing.get("references", [])}
    for item in references:
        if item["id"] in reference_map and reference_map[item["id"]] != item:
            if not args.update_generated:
                raise SystemExit(f"reference registry conflict for {item['id']}")
        reference_map[item["id"]] = item

    outputs = {
        registry_path: dump_yaml({"version": 1, "sources": list(source_map.values()), "references": list(reference_map.values())}),
        root / "data" / "characters.yaml": dump_yaml({"version": 1, "items": char_rows}),
        root / "data" / "components.yaml": dump_yaml({"version": 1, "items": sorted(component_map.values(), key=lambda x: x["id"])}),
        root / "data" / "structures.yaml": dump_yaml({"version": 1, "items": structures}),
        root / "data" / "radicals.yaml": dump_yaml({"version": 1, "items": radicals}),
        root / "data" / "written-forms.yaml": dump_yaml({"version": 1, "items": written_forms}),
        root / "intake" / "source-identity.yaml": dump_yaml({"version": 1, "items": withheld}),
    }
    for path, data in outputs.items():
        if path.exists() or path.is_symlink():
            if path.is_symlink():
                raise SystemExit(f"refusing symlink output: {path}")
            if path.read_bytes() != data and not args.update_generated:
                raise SystemExit(f"generated file differs; pass --update-generated to replace importer output: {path}")
    for path, data in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    print(f"Imported {len(char_rows)} literal identities and structures, {len(component_map)} KanjiVG components, "
          f"{len(radicals)} Kanji Alive radical rows; jōyō={len(expected_joyo)}; withheld={len(withheld)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
