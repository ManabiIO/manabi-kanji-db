#!/usr/bin/env python3
"""Turn the frozen authored TSV batches into traceable, review-pending claims."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

KANJIDIC_SHA256 = "af6fafd267da4c807914420ca2393836e26efa66bf8fe911f6dc967a71283773"
SCOPED_TARGETS = {
    "記": ("kanji-alive-meaning-u8a18", "ka_data.csv[kanji='記']/kmeaning"),
    "曜": ("kanji-alive-meaning-u8a18", "ka_data.csv[kanji='曜']/kmeaning"),
}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def yaml_bytes(value: object) -> bytes:
    return yaml.safe_dump(value, allow_unicode=True, sort_keys=False, width=110, explicit_start=True).encode()


def slug(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return text or "sense"


def exact_sense(groups: list[list[tuple[int, int, str]]], query: str) -> tuple[int, int]:
    q = re.sub(r"[^a-z0-9 ]", " ", query.lower())
    q = " ".join(q.split())
    candidates = [item for group in groups for item in group]
    if not candidates:
        raise ValueError("KANJIDIC2 has no English meaning selectors for this character")
    for group, meaning, text in candidates:
        t = re.sub(r"[^a-z0-9 ]", " ", text.lower())
        t = " ".join(t.split())
        if q == t or q in {piece.strip() for piece in re.split(r"[,;/]", text.lower())}:
            return group, meaning
    q_words = {word for word in q.split() if len(word) > 2}
    scored = []
    for group, meaning, text in candidates:
        t = re.sub(r"[^a-z0-9 ]", " ", text.lower())
        words = set(t.split())
        score = len(q_words & words)
        if q and q in t:
            score += 4
        scored.append((score, group, meaning, text))
    score, group, meaning, _text = max(scored, default=(0, 0, 0, ""))
    if score <= 0:
        # Keep the author-selected sense explicitly queued for human review.
        return candidates[0][:2]
    return group, meaning


def evidence_strokes(structure: dict, chosen: dict) -> list[str]:
    """Return the exact SVG subtree's strokes in stroke order, including child groups."""
    descendants = {chosen["id"]}
    changed = True
    while changed:
        changed = False
        for occurrence in structure["occurrences"]:
            if occurrence["parent"] in descendants and occurrence["id"] not in descendants:
                descendants.add(occurrence["id"])
                changed = True
    strokes = {stroke for occurrence in structure["occurrences"] if occurrence["id"] in descendants
               for stroke in occurrence["strokeIDs"]}
    return sorted(strokes, key=lambda value: int(value[1:]) if value[1:].isdigit() else value)


def kanjidic_senses(path: Path) -> dict[str, list[list[tuple[int, int, str]]]]:
    root = ET.fromstring(gzip.open(path, "rb").read())
    result = {}
    for entry in root.findall("character"):
        literal = entry.findtext("literal")
        if not literal:
            continue
        groups = []
        for gi, group in enumerate(entry.findall("reading_meaning/rmgroup"), start=1):
            meanings = []
            for mi, meaning in enumerate(group.findall("meaning"), start=1):
                if meaning.get("m_lang") in (None, "en") and meaning.text:
                    meanings.append((gi, mi, meaning.text))
            if meanings:
                groups.append(meanings)
        result[literal] = groups
    return result


def source_selector(literal: str, group: int, meaning: int) -> str:
    return f"character[literal={literal!r}]/reading_meaning/rmgroup[{group}]/meaning[{meaning}]"


def source_revision(evidence: list[dict], refs: dict[str, dict]) -> str:
    return "|".join(sorted(f"{refs[item['reference']]['source']}:{refs[item['reference']]['revision']}:{refs[item['reference']]['snapshotHash']}" for item in evidence))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--kanjidic", type=Path, required=True)
    parser.add_argument("--stories", type=Path, action="append", required=True, help="frozen four-column TSV; repeat for another batch")
    parser.add_argument("--cues", type=Path, default=Path("data/story-cue-candidates.tsv"), help="authored visual nickname map")
    parser.add_argument("--update-generated", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if root.is_symlink() or args.kanjidic.is_symlink():
        raise SystemExit("repository root and source inputs must not be symlinks")
    if sha(args.kanjidic.read_bytes()) != KANJIDIC_SHA256:
        raise SystemExit("story target selectors must use the exact pinned KANJIDIC2 bytes")
    registry = yaml.safe_load((root / "sources/registry.yaml").read_text(encoding="utf-8"))
    refs = {ref["id"]: ref for ref in registry["references"]}
    structures = yaml.safe_load((root / "data/structures.yaml").read_text(encoding="utf-8"))["items"]
    structure_by_literal = {item["literal"]: item for item in structures}
    sense_map = kanjidic_senses(args.kanjidic)
    cue_path = (root / args.cues).resolve(strict=True) if not args.cues.is_absolute() else args.cues.resolve(strict=True)
    if cue_path.is_symlink() or cue_path.parent != (root / "data").resolve(strict=True):
        raise SystemExit("story cue input must be a non-symlink file directly under data/")
    cue_hash = sha(cue_path.read_bytes())

    rows = []
    inputs = [{"batch": cue_path.name, "sha256": cue_hash}]
    for input_path in args.stories:
        if not input_path.is_file() or input_path.is_symlink():
            raise SystemExit(f"missing or symlink story batch: {input_path}")
        inputs.append({"batch": input_path.stem, "sha256": sha(input_path.read_bytes())})
        with input_path.open(encoding="utf-8", newline="") as stream:
            for lineno, fields in enumerate(csv.reader(stream, delimiter="\t"), start=1):
                if len(fields) != 4:
                    raise SystemExit(f"{input_path}:{lineno}: expected literal, components, target sense, story")
                literal, component_list, target_gloss, text = fields
                if len(literal) != 1 or not component_list or not target_gloss or not text:
                    raise SystemExit(f"{input_path}:{lineno}: required field is empty or literal is not one Unicode scalar")
                rows.append({"literal": literal, "components": component_list.split("+"), "target": target_gloss, "text": text})
    if len(rows) < 100 or len({row["literal"] for row in rows}) != len(rows):
        raise SystemExit(f"expected at least 100 distinct character stories, received {len(rows)}")

    claims: dict[str, dict] = {}
    story_claims: list[dict] = []
    issues: list[str] = []
    sense_choices = []
    for row in rows:
        literal = row["literal"]
        structure = structure_by_literal.get(literal)
        if structure is None:
            issues.append(f"U+{ord(literal):04X}: no imported Japanese structure")
            continue
        root_occ = next((occ for occ in structure["occurrences"] if occ["parent"] is None), None)
        root_id = root_occ["id"] if root_occ else None
        available = [occ for occ in structure["occurrences"] if occ["id"] != root_id]
        used: set[str] = set()
        story_occurrences = []
        target_reference, target_sel = SCOPED_TARGETS.get(literal, ("kanjidic2-identity-snapshot", ""))
        story_evidence = [{"reference": target_reference, "claimField": "story.targetReference",
                           "supportType": "exact-source-meaning-selector", "selector": target_sel}]
        component_refs = []
        for part in row["components"]:
            chosen = next((occ for occ in available if occ["id"] not in used and occ["form"] == part), None)
            crosswalk = None
            if chosen is None:
                chosen = next((occ for occ in available if occ["id"] not in used and occ["attributes"].get("original") == part), None)
                if chosen:
                    crosswalk = {"fromCodepoint": f"U+{ord(chosen['form']):04X}", "toCodepoint": f"U+{ord(part):04X}",
                                 "sourceAttribute": "original", "reference": structure["reference"]}
            if chosen is None:
                issues.append(f"U+{ord(literal):04X}: no distinct source occurrence for authored component {part!r}")
                continue
            used.add(chosen["id"])
            source_component = part
            component_id = chosen["component"]
            stroke_selector = f"{chosen['sourceID']}; strokes={','.join(evidence_strokes(structure, chosen))}"
            from story_labels import component_label
            label_text = component_label(chosen["form"], part, literal, chosen["attributes"])
            label_reference = structure["reference"]
            label_selector = stroke_selector
            label_id = f"visual-u{ord(chosen['form']):x}-{slug(label_text)}"
            label_evidence = [
                {"reference": label_reference, "claimField": "claimText", "supportType": "selected-component-label", "selector": label_selector},
                {"reference": structure["reference"], "claimField": "subject", "supportType": "visible-japanese-form", "selector": stroke_selector},
            ]
            label_revision = sha(json.dumps({"id": label_id, "text": label_text, "selector": label_selector},
                                             ensure_ascii=False, sort_keys=True).encode())
            if label_id not in claims:
                claims[label_id] = {
                    "id": label_id, "kind": "visual-name", "subject": {"type": "component", "id": component_id},
                    "revision": label_revision, "localizedRevision": label_revision, "status": "candidate",
                    "claimText": label_text, "targetLanguage": "ja", "locale": "en",
                    "author": {"name": "Manabi Kanji DB import adapter", "type": "agent", "recordedAt": "2026-11-27"},
                    "license": "CC-BY-SA-4.0", "evidence": label_evidence,
                    "review": {"state": "pending"},
                }
            if claims[label_id]["subject"]["id"] != component_id:
                raise SystemExit(f"visual-label ID collision: {label_id}")
            story_occurrences.append({"structure": structure["id"], "occurrence": chosen["id"], "labelClaim": label_id,
                                      "authoredForm": part, "crosswalk": crosswalk})
            story_evidence.append({"reference": structure["reference"], "claimField": f"story.occurrences[{len(story_occurrences)-1}]",
                                   "supportType": "exact-component-occurrence", "selector": stroke_selector})
            component_refs.append({"part": part, "actualForm": chosen["form"], "occurrence": chosen["sourceID"],
                                   "labelClaim": label_id, "label": label_text, "crosswalk": crosswalk})

        if len(story_occurrences) != len(row["components"]):
            continue
        if not target_sel:
            target_groups = sense_map.get(literal, [])
            if not target_groups:
                issues.append(f"U+{ord(literal):04X}: no KANJIDIC2 English target meaning")
                continue
            target_group, target_index = exact_sense(target_groups, row["target"])
            target_sel = source_selector(literal, target_group, target_index)
            story_evidence[0]["selector"] = target_sel
        target_revision = sha(row["text"].encode("utf-8"))
        story_id = f"story-en-u{ord(literal):x}"
        claim_revision = sha(json.dumps({"id": story_id, "text": row["text"], "targetSelector": target_sel,
                                         "occurrences": story_occurrences}, ensure_ascii=False, sort_keys=True).encode())
        story = {
            "id": story_id, "kind": "mnemonic", "subject": {"type": "character", "literal": literal,
                                                                 "codepoint": f"U+{ord(literal):04X}"},
            "revision": claim_revision, "localizedRevision": target_revision, "status": "candidate",
            "claimText": row["text"], "targetLanguage": "ja", "locale": "en",
            "author": {"name": "OpenAI Codex agent /root/stories", "type": "agent", "recordedAt": "2026-11-27"},
            "license": "CC-BY-SA-4.0", "evidence": story_evidence,
            "review": {"state": "pending"},
            "story": {"locale": "en", "originality": "original", "targetReference": target_reference,
                      "targetSelector": target_sel,
                      "occurrences": story_occurrences, "fiction": True, "textRevision": target_revision},
        }
        story_claims.append(story)
        sense_choices.append({"literal": literal, "targetCandidate": row["target"],
                              "selector": target_sel, "components": component_refs, "storyClaim": story_id})

    if issues:
        raise SystemExit("story import needs source/editorial decisions before writing:\n" + "\n".join(issues[:60]))
    all_claims = list(claims.values()) + story_claims
    out: dict[Path, bytes] = {}
    manifest = {"version": 1, "author": "OpenAI Codex agent /root/stories", "license": "CC-BY-SA-4.0",
                "status": "candidate-pending-distinct-review", "sourceInputs": inputs,
                "storyCount": len(story_claims), "distinctComponentLabelClaims": len(claims),
                "claims": [{"id": claim["id"], "kind": claim["kind"], "revision": claim["revision"],
                            "localizedRevision": claim["localizedRevision"]} for claim in all_claims],
                "targetSenseSelectors": sense_choices}
    out[root / "data" / "story-seed-manifest.yaml"] = yaml_bytes(manifest)
    for claim in sorted(claims.values(), key=lambda item: item["id"]):
        out[root / "content" / "labels" / f"{claim['id']}.yaml"] = yaml_bytes(claim)
    for claim in sorted(story_claims, key=lambda item: item["id"]):
        out[root / "content" / "stories" / "en" / f"{claim['id']}.yaml"] = yaml_bytes(claim)
    for path, content in out.items():
        if path.exists() or path.is_symlink():
            if path.is_symlink():
                raise SystemExit(f"refusing symlink output: {path}")
            if path.read_bytes() != content and not args.update_generated:
                raise SystemExit(f"generated claim differs; pass --update-generated to replace it: {path}")
    for path, content in out.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists() or path.read_bytes() != content:
            path.write_bytes(content)
    print(f"Generated {len(story_claims)} original story claims and {len(claims)} sourced visual-label candidates; all remain pending independent review")
    print(f"Candidate review projection: data/story-seed-manifest.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
