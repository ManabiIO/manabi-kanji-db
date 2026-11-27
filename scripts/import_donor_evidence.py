"""Bind the licensed donor lessons to the pinned public passages they use."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import yaml

ORIGIN_PIN = "58cf079cc98f8a134d34ba8b7fd4d3c02f0a4f314fef460ac69abdd94231931a"
SOURCE = "enwiktionary-glyph-origin"
ROLE_KINDS = {"Meaning": "semantic-function", "Sound": "historical-phonetic", "Picture": "historical-origin"}


def digest(value):
    return hashlib.sha256(value).hexdigest()


def revision(value):
    return digest(json.dumps(value, sort_keys=True, ensure_ascii=False).encode())


def output_yaml(value):
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=110)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("passages", type=Path, help="pinned wiktionary-glyph-origin.json.gz")
    args = parser.parse_args()
    data = args.passages.read_bytes()
    if digest(data) != ORIGIN_PIN:
        parser.error("Wiktionary passage archive SHA-256 does not match the source pin")
    pages = json.loads(gzip.decompress(data))["records"]
    root = Path(__file__).resolve().parents[1]
    registry_file = root / "sources/registry.yaml"
    registry = yaml.safe_load(registry_file.read_text())
    source = dict(id=SOURCE, author="English Wiktionary contributors", project="English Wiktionary",
                  url="https://en.wiktionary.org/wiki/Wiktionary:Main_Page", license="CC-BY-SA",
                  licenseVersion="4.0", licenseEvidenceURL="https://en.wiktionary.org/wiki/Wiktionary:Copyrights",
                  scope="Revision-pinned Glyph origin passages as factual references; passage text and images excluded",
                  attribution="English Wiktionary contributors, linked article histories",
                  modifications="Selected section identities and hashes. No article bodies distributed.",
                  sourceLanguage="en", upstream=[], revision="per-article oldid",
                  acquisitionMethod="Verified cached UTF-8 passage bytes from revision-specific pages",
                  retrievedAt="2026-11-27T00:00:00Z", sha256=ORIGIN_PIN)
    rows = [json.loads(s) for s in (root / "data/imports/donor-v26.jsonl").read_text().splitlines()]
    references = {}
    manifest = []
    for row in rows:
        key, value = row["payload"]["key"], row["payload"]["value"]
        if not isinstance(value, dict) or "source" not in value:
            continue
        identity = value["source"]
        literal = key.split("/")[0]
        title = value.get("sourceCharacter", literal)
        page = pages[title]
        if (page["revisionID"], page["pageSHA256"]) != (identity["revisionID"], identity["pageSHA256"]):
            raise ValueError(f"{key}: revision or page hash mismatch")
        section, = [s for s in page["sections"] if s["language"] == identity["language"]
                    and s["sectionSHA256"] == identity["sectionSHA256"]]
        if digest(section["wikitext"].encode()) != section["sectionSHA256"]:
            raise ValueError(f"{key}: passage bytes disagree with cached hash")
        oldid = str(page["revisionID"])
        ref_id = f"wikt-origin-{oldid}-{section['sectionSHA256'][:12]}"
        selector = f"{section['language']} / Glyph origin"
        references[ref_id] = dict(id=ref_id, source=SOURCE,
            url=f"https://en.wiktionary.org/w/index.php?title={quote(title)}&oldid={oldid}#Glyph_origin",
            externalId=title, locator=selector, revision=oldid, snapshotHash=section["sectionSHA256"],
            retrievedAt=source["retrievedAt"], supports=["Historical formation under the cited language heading"])
        item = dict(candidate=row["id"], character=literal, reference=ref_id, selector=selector,
                    pageSHA256=page["pageSHA256"], sectionSHA256=section["sectionSHA256"])
        manifest.append(item)
        category = row["kind"].removeprefix("donor-v26-")
        if category == "wholeCharacterLessons":
            kind, text = "historical-origin", value["text"]
            subject = dict(type="character", literal=literal, codepoint=f"U+{ord(literal):04X}")
        elif category == "occurrenceReviews":
            kind, text = ROLE_KINDS[value["role"]], value["explanation"]
            subject = dict(type="occurrence", structure=f"kv-{ord(literal):x}", occurrence=value["id"])
        else:
            continue
        name = f"donor-{row['id'].removeprefix('cand-')}"
        evidence = [
            dict(reference=ref_id, claimField="claimText", supportType="factual-evidence", selector=selector),
            dict(reference=row["reference"], claimField="claimText", supportType="adapted-wording", selector=row["selector"]),
        ]
        if subject["type"] == "occurrence":
            evidence.append(dict(reference=f"kanjivg-{ord(literal):x}", claimField="subject",
                                 supportType="visible-japanese-form", selector=value["id"]))
        claim = dict(id=name, kind=kind, subject=subject,
                     revision=revision([kind, subject, evidence, text]), localizedRevision=digest(text.encode()),
                     status="candidate", claimText=text, targetLanguage="ja", locale="en",
                     author=dict(name="Manabi KanjiExplanation contributors", type="community", recordedAt="2026-11-27"),
                     license="CC-BY-SA-4.0", evidence=evidence, review=dict(state="pending"))
        item["claim"] = name
        target = root / "content/donor" / (name + ".yaml")
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            with target.open("x", encoding="utf-8") as file:
                file.write(output_yaml(claim))
    # Keep the original registry formatting and preserve all editorial changes.
    existing_sources = {s["id"] for s in registry["sources"]}
    existing_references = {r["id"]: r for r in registry["references"]}
    original = registry_file.read_text()
    new_registry = original
    if SOURCE not in existing_sources:
        new_registry = original.replace("\nreferences:\n", "\n" + output_yaml([source]) + "references:\n", 1)
        if new_registry == original:
            raise ValueError("cannot locate references collection")
    additions = []
    for key, ref in sorted(references.items()):
        if key not in existing_references:
            additions.append(ref)
        elif existing_references[key] != ref:
            raise ValueError(f"{key}: existing reference differs from pinned input")
    if additions:
        new_registry += output_yaml(additions)
    if new_registry != original:
        registry_file.write_text(new_registry)
    target = root / "data/coverage/donor-passages.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"{len(manifest)} verified passage bindings; {len(references)} exact public references")


if __name__ == "__main__":
    main()
