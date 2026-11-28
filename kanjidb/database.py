from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from .validation import ValidationError, load_project, validate, need, exact_keys, nonempty, is_scalar
from .yamlio import load

SCHEMA_VERSION = 4

DDL = """
PRAGMA foreign_keys = ON;
PRAGMA page_size = 4096;
PRAGMA auto_vacuum = NONE;
CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL) STRICT;
CREATE TABLE source(
  id TEXT PRIMARY KEY, author TEXT NOT NULL, project TEXT NOT NULL, url TEXT NOT NULL,
  license TEXT NOT NULL, license_version TEXT NOT NULL, license_evidence_url TEXT NOT NULL, scope TEXT NOT NULL,
  attribution TEXT NOT NULL, modifications TEXT NOT NULL, source_language TEXT NOT NULL,
  upstream_json TEXT NOT NULL CHECK(json_valid(upstream_json)), revision TEXT NOT NULL,
  sha256 TEXT, acquisition_method TEXT NOT NULL, retrieved_at TEXT NOT NULL
) STRICT;
CREATE TABLE reference(
  id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES source(id), url TEXT NOT NULL,
  external_id TEXT NOT NULL, locator TEXT NOT NULL, revision TEXT NOT NULL,
  snapshot_hash TEXT NOT NULL, retrieved_at TEXT NOT NULL,
  supports_json TEXT NOT NULL CHECK(json_valid(supports_json))
) STRICT;
CREATE INDEX reference_source ON reference(source_id);
CREATE TABLE character(
  literal TEXT PRIMARY KEY CHECK(length(literal) = 1), codepoint TEXT NOT NULL UNIQUE,
  baseline_source_id TEXT NOT NULL REFERENCES source(id), baseline_revision TEXT NOT NULL,
  baseline_reference_id TEXT NOT NULL REFERENCES reference(id)
) STRICT;
CREATE TABLE component(
  id TEXT PRIMARY KEY, form TEXT NOT NULL, kind TEXT NOT NULL,
  source_id TEXT NOT NULL REFERENCES source(id), source_revision TEXT NOT NULL,
  reference_id TEXT NOT NULL REFERENCES reference(id)
) STRICT;
CREATE INDEX component_form ON component(form);
CREATE TABLE structure(
  id TEXT PRIMARY KEY, literal TEXT NOT NULL REFERENCES character(literal),
  source_id TEXT NOT NULL REFERENCES source(id), source_revision TEXT NOT NULL,
  source_selector TEXT NOT NULL, variant TEXT NOT NULL DEFAULT 'ja', reference_id TEXT NOT NULL REFERENCES reference(id)
) STRICT;
CREATE INDEX structure_literal ON structure(literal);
CREATE TABLE occurrence(
  structure_id TEXT NOT NULL REFERENCES structure(id), occurrence_id TEXT NOT NULL,
  component_id TEXT NOT NULL REFERENCES component(id), parent_id TEXT,
  ordinal INTEGER NOT NULL, group_id TEXT NOT NULL, stroke_ids_json TEXT NOT NULL CHECK(json_valid(stroke_ids_json)),
  visible_form TEXT NOT NULL, source_attributes_json TEXT NOT NULL CHECK(json_valid(source_attributes_json)),
  PRIMARY KEY(structure_id, occurrence_id),
  FOREIGN KEY(structure_id, parent_id) REFERENCES occurrence(structure_id, occurrence_id)
) STRICT;
CREATE INDEX occurrence_component ON occurrence(component_id);
CREATE INDEX occurrence_visible_form_lookup ON occurrence(visible_form, structure_id, occurrence_id);
CREATE TABLE radical_name(
  id TEXT PRIMARY KEY, literal TEXT NOT NULL, codepoint TEXT NOT NULL, kangxi_number TEXT,
  english_meaning TEXT, reading_kana TEXT, reading_romanized TEXT,
  position_japanese TEXT, position_romanized TEXT, importance TEXT, origin TEXT,
  variant_of TEXT, variant_of_id TEXT, source_id TEXT NOT NULL REFERENCES source(id),
  source_revision TEXT NOT NULL, source_reference TEXT NOT NULL REFERENCES reference(id),
  ids_reference TEXT NOT NULL REFERENCES reference(id), source_row INTEGER NOT NULL,
  source_status TEXT NOT NULL, japanese_applicability TEXT NOT NULL
) STRICT;
CREATE INDEX radical_name_literal ON radical_name(literal);
CREATE TABLE written_form_pair(
  id TEXT PRIMARY KEY, new_form TEXT NOT NULL, new_codepoint TEXT NOT NULL,
  old_form TEXT NOT NULL, old_codepoint TEXT NOT NULL, categories_json TEXT NOT NULL CHECK(json_valid(categories_json)),
  source_occurrences_json TEXT NOT NULL CHECK(json_valid(source_occurrences_json)),
  source_id TEXT NOT NULL REFERENCES source(id), source_revision TEXT NOT NULL,
  reference_id TEXT NOT NULL REFERENCES reference(id), source_status TEXT NOT NULL,
  official_status TEXT NOT NULL, new_structure_available INTEGER NOT NULL CHECK(new_structure_available IN (0,1)),
  old_structure_available INTEGER NOT NULL CHECK(old_structure_available IN (0,1)),
  UNIQUE(new_codepoint, old_codepoint)
) STRICT;
CREATE INDEX written_form_new ON written_form_pair(new_form);
CREATE INDEX written_form_old ON written_form_pair(old_form);
CREATE TABLE joyo_appendix_reading(
  id TEXT PRIMARY KEY, spelling TEXT NOT NULL, reading TEXT NOT NULL,
  source_row INTEGER NOT NULL, role TEXT NOT NULL CHECK(role IN ('primary','alternate','example')),
  source_id TEXT NOT NULL REFERENCES source(id), source_revision TEXT NOT NULL,
  reference_id TEXT NOT NULL REFERENCES reference(id),
  UNIQUE(source_row, spelling, reading, role)
) STRICT;
CREATE INDEX joyo_appendix_spelling_reading ON joyo_appendix_reading(spelling, reading);
CREATE TABLE joyo_appendix_jmdict_entry(
  reading_id TEXT NOT NULL REFERENCES joyo_appendix_reading(id),
  entry_id INTEGER NOT NULL CHECK(entry_id > 0),
  reference_id TEXT NOT NULL REFERENCES reference(id),
  PRIMARY KEY(reading_id, entry_id)
) STRICT;
CREATE INDEX joyo_appendix_jmdict_entry_lookup ON joyo_appendix_jmdict_entry(entry_id);
CREATE VIEW official_joyo_appendix_reading AS
  SELECT r.id, r.spelling, r.reading, r.source_row, r.role,
         r.source_id, r.source_revision, r.reference_id,
         j.entry_id AS jmdict_entry_id, j.reference_id AS jmdict_reference_id,
         jr.source_id AS jmdict_source_id
  FROM joyo_appendix_reading r
  LEFT JOIN joyo_appendix_jmdict_entry j ON j.reading_id=r.id
  LEFT JOIN reference jr ON jr.id=j.reference_id;
CREATE TABLE intake(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject_json TEXT NOT NULL CHECK(json_valid(subject_json)),
  references_json TEXT NOT NULL CHECK(json_valid(references_json)), reason TEXT NOT NULL,
  next_action TEXT NOT NULL, disposition TEXT NOT NULL, publishable INTEGER NOT NULL CHECK(publishable = 0)
) STRICT;
CREATE TABLE imported_candidate(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject_json TEXT NOT NULL CHECK(json_valid(subject_json)),
  payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), source_id TEXT NOT NULL REFERENCES source(id),
  source_revision TEXT NOT NULL, reference_id TEXT NOT NULL REFERENCES reference(id), selector TEXT NOT NULL,
  source_status TEXT NOT NULL, japanese_applicability TEXT NOT NULL, review_state TEXT NOT NULL,
  publishable INTEGER NOT NULL CHECK(publishable = 0)
) STRICT;
CREATE INDEX imported_candidate_kind_subject ON imported_candidate(kind, source_status);
CREATE TABLE candidate_relation(
  candidate_id TEXT NOT NULL REFERENCES imported_candidate(id), ordinal INTEGER NOT NULL,
  relation_kind TEXT NOT NULL, component_form TEXT, character_literal TEXT,
  related_literal TEXT, reading_candidate TEXT, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
  PRIMARY KEY(candidate_id, ordinal),
  CHECK(character_literal IS NULL OR length(character_literal) = 1),
  CHECK(related_literal IS NULL OR length(related_literal) = 1)
) STRICT;
CREATE INDEX candidate_relation_component ON candidate_relation(component_form, relation_kind);
CREATE INDEX candidate_relation_character ON candidate_relation(character_literal, relation_kind);
CREATE INDEX candidate_relation_related ON candidate_relation(related_literal, relation_kind);
CREATE TABLE asset(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT NOT NULL, path TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL, source_id TEXT NOT NULL REFERENCES source(id), source_revision TEXT NOT NULL,
  description_reference_id TEXT NOT NULL REFERENCES reference(id), media_reference_id TEXT NOT NULL REFERENCES reference(id),
  license TEXT NOT NULL, license_evidence_url TEXT NOT NULL, attribution TEXT NOT NULL,
  status TEXT NOT NULL, review_state TEXT NOT NULL, script_label TEXT NOT NULL,
  selector TEXT NOT NULL, date_is_upload_date_only INTEGER NOT NULL CHECK(date_is_upload_date_only IN (0,1))
) STRICT;
CREATE INDEX asset_subject_kind_status ON asset(subject, kind, status);
CREATE TABLE claim(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, subject_type TEXT NOT NULL, subject_id TEXT NOT NULL,
  subject_structure_id TEXT, subject_literal TEXT, subject_codepoint TEXT, revision TEXT NOT NULL,
  status TEXT NOT NULL, target_language TEXT NOT NULL, author TEXT NOT NULL,
  license TEXT NOT NULL, review_state TEXT NOT NULL, reviewer TEXT, review_date TEXT,
  review_claim_revision TEXT, review_source_revision TEXT, review_rationale TEXT,
  CHECK((subject_type = 'occurrence') = (subject_structure_id IS NOT NULL)),
  FOREIGN KEY(subject_structure_id, subject_id) REFERENCES occurrence(structure_id, occurrence_id)
) STRICT;
CREATE INDEX claim_subject_kind_status ON claim(subject_type, subject_id, kind, status);
CREATE INDEX claim_occurrence_subject ON claim(subject_structure_id, subject_id) WHERE subject_type = 'occurrence';
CREATE INDEX claim_approved_occurrence_role ON claim(subject_structure_id, subject_id, kind)
  WHERE subject_type = 'occurrence' AND status = 'approved' AND review_state = 'approved';
CREATE TABLE claim_evidence(
  claim_id TEXT NOT NULL REFERENCES claim(id), reference_id TEXT NOT NULL REFERENCES reference(id),
  claim_field TEXT NOT NULL, support_type TEXT NOT NULL, selector TEXT NOT NULL,
  PRIMARY KEY(claim_id, reference_id, claim_field, support_type, selector)
) STRICT;
CREATE INDEX claim_evidence_reference ON claim_evidence(reference_id);
CREATE TABLE story(
  claim_id TEXT PRIMARY KEY REFERENCES claim(id), target_reference_id TEXT NOT NULL REFERENCES reference(id), target_selector TEXT NOT NULL,
  originality TEXT NOT NULL, fictional INTEGER NOT NULL CHECK(fictional = 1), text_revision TEXT NOT NULL
) STRICT;
CREATE TABLE story_occurrence(
  claim_id TEXT NOT NULL REFERENCES story(claim_id), ordinal INTEGER NOT NULL,
  structure_id TEXT NOT NULL, occurrence_id TEXT NOT NULL, label_claim_id TEXT NOT NULL REFERENCES claim(id),
  authored_form TEXT NOT NULL, crosswalk_json TEXT CHECK(crosswalk_json IS NULL OR json_valid(crosswalk_json)),
  PRIMARY KEY(claim_id, ordinal),
  FOREIGN KEY(structure_id, occurrence_id) REFERENCES occurrence(structure_id, occurrence_id)
) STRICT;
CREATE TABLE localized_text(
  claim_id TEXT NOT NULL REFERENCES claim(id), locale TEXT NOT NULL, revision TEXT NOT NULL,
  text TEXT NOT NULL, translation_of_claim TEXT REFERENCES claim(id),
  translation_source_locale TEXT, translation_source_revision TEXT, stale INTEGER NOT NULL CHECK(stale IN (0,1)),
  PRIMARY KEY(claim_id, locale)
) STRICT;
CREATE INDEX localized_text_locale ON localized_text(locale, claim_id);
CREATE VIEW current_approved_claim AS
  SELECT c.*, t.locale, t.revision AS text_revision, t.text
  FROM claim c JOIN localized_text t ON t.claim_id=c.id
  WHERE c.status = 'approved' AND c.review_state = 'approved'
    AND c.review_claim_revision = c.revision AND t.stale = 0;
CREATE VIEW visible_component_occurrence AS
  SELECT s.literal, o.structure_id, o.occurrence_id, o.component_id, o.parent_id,
         o.visible_form, o.group_id, o.stroke_ids_json, o.source_attributes_json
  FROM occurrence o JOIN structure s ON s.id=o.structure_id;
CREATE VIEW approved_component_role AS
  SELECT s.literal AS character_literal, o.structure_id, o.occurrence_id, o.component_id,
         o.visible_form, c.kind AS role_kind, c.id AS claim_id, t.locale, t.text
  FROM occurrence o
  CROSS JOIN structure s ON s.id=o.structure_id
  CROSS JOIN claim c ON c.subject_structure_id=o.structure_id AND c.subject_id=o.occurrence_id
  JOIN localized_text t ON t.claim_id=c.id
  WHERE c.subject_type='occurrence' AND c.status='approved' AND c.review_state='approved'
    AND c.review_claim_revision=c.revision AND t.stale=0
    AND c.kind IN ('semantic-function', 'historical-phonetic', 'modern-japanese-sound');
CREATE VIEW candidate_component_relationship AS
  SELECT r.*, c.source_id, c.source_revision, c.reference_id, c.source_status, c.japanese_applicability, c.review_state
  FROM candidate_relation r JOIN imported_candidate c ON c.id=r.candidate_id
  WHERE r.component_form IS NOT NULL;
CREATE VIEW candidate_character_relationship AS
  SELECT r.*, c.source_id, c.source_revision, c.reference_id, c.source_status, c.japanese_applicability, c.review_state
  FROM candidate_relation r JOIN imported_candidate c ON c.id=r.candidate_id
  WHERE r.character_literal IS NOT NULL OR r.related_literal IS NOT NULL;
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def input_files(root: Path) -> list[Path]:
    paths = [root / "sources" / "registry.yaml"]
    paths.extend(sorted((root / "content").rglob("*.yaml")))
    paths.extend(sorted((root / "data").rglob("*.yaml")))
    paths.extend(sorted((root / "intake").rglob("*.yaml")))
    for pattern in ("*.jsonl", "*.json", "*.tsv", "*.txt"):
        paths.extend(path for path in sorted((root / "data" / "imports").rglob(pattern))
                     if "source-files" not in path.relative_to(root / "data" / "imports").parts)
    paths.extend(sorted((root / "assets").rglob("*")))
    paths.extend(sorted((root / "source-notices").rglob("*")))
    paths.extend(root / name for name in ("pyproject.toml", "requirements.txt", "requirements-lock.txt"))
    return [path for path in paths if path.is_file() and not path.is_symlink()]


def input_manifest(root: Path) -> list[dict[str, str]]:
    rows = []
    for path in input_files(root):
        content = path.read_bytes()
        rows.append({"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(content).hexdigest()})
    return rows


def _imports(root: Path, sources: dict[str, dict]) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    registry = load(root / "sources" / "registry.yaml")
    refs = {item["id"]: item for item in registry["references"]}
    characters = load(root / "data" / "characters.yaml") if (root / "data" / "characters.yaml").exists() else {"version": 1, "items": []}
    components = load(root / "data" / "components.yaml") if (root / "data" / "components.yaml").exists() else {"version": 1, "items": []}
    structures = load(root / "data" / "structures.yaml") if (root / "data" / "structures.yaml").exists() else {"version": 1, "items": []}
    radicals = load(root / "data" / "radicals.yaml") if (root / "data" / "radicals.yaml").exists() else {"version": 1, "items": []}
    written_forms = load(root / "data" / "written-forms.yaml") if (root / "data" / "written-forms.yaml").exists() else {"version": 1, "items": []}
    joyo_readings = load(root / "data" / "joyo-appendix.yaml") if (root / "data" / "joyo-appendix.yaml").exists() else {"version": 1, "items": []}
    for name, doc in (("characters", characters), ("components", components), ("structures", structures), ("radicals", radicals), ("written-forms", written_forms), ("joyo-appendix", joyo_readings)):
        p = root / "data" / f"{name}.yaml"
        exact_keys(doc, {"version", "items"}, p)
        need(doc.get("version") == 1 and isinstance(doc.get("items"), list), p, "$", "requires version 1 and an items list")
    char_by_literal: dict[str, dict] = {}
    for i, row in enumerate(characters["items"]):
        p, f = root / "data" / "characters.yaml", f"items[{i}]"
        exact_keys(row, {"literal", "codepoint", "source", "revision", "baseline", "reference"}, p, f)
        literal = row.get("literal")
        need(isinstance(literal, str) and len(literal) == 1, p, f + ".literal", "must be one literal Unicode scalar")
        need(row.get("codepoint") == f"U+{ord(literal):04X}", p, f + ".codepoint", "must be the literal's Unicode codepoint")
        need(row.get("source") in sources, p, f + ".source", "unknown source")
        need(row.get("reference") in refs and refs[row["reference"]]["source"] == row["source"], p, f + ".reference", "must resolve to this source's exact identity snapshot")
        nonempty(row.get("revision"), p, f + ".revision")
        exact_keys(row.get("baseline"), {"literal", "codepoint"}, p, f + ".baseline")
        need(row["baseline"] == {"literal": literal, "codepoint": row["codepoint"]}, p, f + ".baseline", "baseline join must use literal and codepoint only")
        need(literal not in char_by_literal, p, f + ".literal", "duplicate character")
        char_by_literal[literal] = row
    component_by_id: dict[str, dict] = {}
    for i, row in enumerate(components["items"]):
        p, f = root / "data" / "components.yaml", f"items[{i}]"
        exact_keys(row, {"id", "form", "kind", "source", "revision", "reference"}, p, f)
        need(isinstance(row.get("id"), str) and row["id"].startswith("cmp-"), p, f + ".id", "must use stable cmp- namespaced identity")
        need(row.get("kind") in {"encoded", "unencoded", "variant", "group"}, p, f + ".kind", "unknown component form kind")
        need(isinstance(row.get("form"), str), p, f + ".form", "must be a string; unnamed source groups use the empty string")
        need(bool(row["form"]) or row["kind"] == "group", p, f + ".form", "only an unnamed source group may have an empty form")
        need(row.get("source") in sources, p, f + ".source", "unknown source")
        need(row.get("reference") in refs and refs[row["reference"]]["source"] == row["source"], p, f + ".reference", "must resolve to this source's exact component evidence")
        nonempty(row.get("reference"), p, f + ".reference")
        nonempty(row.get("revision"), p, f + ".revision")
        need(row["id"] not in component_by_id, p, f + ".id", "duplicate component id")
        component_by_id[row["id"]] = row
    structures_by_id: dict[str, dict] = {}
    occurrence_index: dict[tuple[str, str], dict] = {}
    for i, row in enumerate(structures["items"]):
        p, f = root / "data" / "structures.yaml", f"items[{i}]"
        exact_keys(row, {"id", "literal", "source", "revision", "selector", "variant", "reference", "occurrences"}, p, f)
        nonempty(row.get("id"), p, f + ".id")
        need(row.get("literal") in char_by_literal, p, f + ".literal", "character must exist in KANJIDIC identity table")
        need(row.get("source") in sources, p, f + ".source", "unknown source")
        need(row.get("reference") in refs and refs[row["reference"]]["source"] == row["source"], p, f + ".reference", "must resolve to this structure's exact source file")
        for key in ("revision", "selector", "variant"):
            nonempty(row.get(key), p, f + ".{key}")
        need(isinstance(row.get("occurrences"), list) and row["occurrences"], p, f + ".occurrences", "must list exact decomposition occurrences")
        need(row["id"] not in structures_by_id, p, f + ".id", "duplicate structure ID")
        structures_by_id[row["id"]] = row
        local = set()
        for j, occ in enumerate(row["occurrences"]):
            of = f"{f}.occurrences[{j}]"
            exact_keys(occ, {"id", "component", "parent", "ordinal", "group", "strokeIDs", "form", "sourceID", "attributes"}, p, of)
            nonempty(occ.get("id"), p, of + ".id")
            need(occ.get("component") in component_by_id, p, of + ".component", "unknown component ID")
            need(occ.get("parent") is None or occ.get("parent") in local, p, of + ".parent", "parent occurrence must precede its child")
            need(isinstance(occ.get("ordinal"), int) and occ["ordinal"] >= 0, p, of + ".ordinal", "must be a nonnegative integer")
            nonempty(occ.get("group"), p, of + ".group")
            need(isinstance(occ.get("strokeIDs"), list) and all(isinstance(x, str) and x for x in occ["strokeIDs"]), p, of + ".strokeIDs", "must preserve source stroke selectors")
            need(isinstance(occ.get("form"), str), p, of + ".form", "must be a source form string (empty means the source group has no encoded element)")
            nonempty(occ.get("sourceID"), p, of + ".sourceID")
            need(isinstance(occ.get("attributes"), dict) and all(isinstance(k, str) and isinstance(v, str) for k,v in occ["attributes"].items()), p, of + ".attributes", "must preserve string-valued source attributes")
            need(occ["id"] not in local, p, of + ".id", "duplicate occurrence ID")
            local.add(occ["id"])
            occurrence_index[(row["id"], occ["id"])] = occ
    # Every parent target is exact and stays within one source decomposition.
    for i, row in enumerate(radicals["items"]):
        p, f = root / "data" / "radicals.yaml", f"items[{i}]"
        exact_keys(row, {"id", "literal", "codepoint", "kangxiNumber", "englishMeaning", "readingKana", "readingRomanized", "positionJapanese", "positionRomanized", "importance", "origin", "variantOf", "variantOfReading", "variantOfId", "source", "revision", "reference", "idsReference", "sourceRow", "sourceStatus", "japaneseApplicability", "baselineIdentityAvailable"}, p, f)
        need(isinstance(row.get("literal"), str) and len(row["literal"]) == 1, p, f + ".literal", "must be one exact radical Unicode scalar")
        need(row.get("codepoint") == f"U+{ord(row['literal']):04X}", p, f + ".codepoint", "must match exact source literal")
        need(row.get("source") in sources, p, f + ".source", "unknown source")
        for key in ("reference", "idsReference"):
            nonempty(row.get(key), p, f + ".{key}")
            need(row[key] in refs and refs[row[key]]["source"] == row["source"], p, f + ".{key}", "must resolve to the exact Kanji Alive source file")
        need(row.get("sourceRow", 0) >= 2, p, f + ".sourceRow", "must identify its CSV row")
        need(row.get("sourceStatus") == "candidate" and row.get("japaneseApplicability") == "unreviewed", p, f, "imported radical names remain candidates until Japanese review")
    pair_ids: set[str] = set()
    for i, row in enumerate(written_forms["items"]):
        p, f = root / "data" / "written-forms.yaml", f"items[{i}]"
        exact_keys(row, {"id", "newForm", "newCodepoint", "oldForm", "oldCodepoint", "categories", "sourceOccurrences", "source", "revision", "reference", "sourceStatus", "officialStatus", "newStructureAvailable", "oldStructureAvailable"}, p, f)
        for form_field, cp_field in (("newForm", "newCodepoint"), ("oldForm", "oldCodepoint")):
            form = row.get(form_field)
            need(isinstance(form, str) and len(form) == 1, p, f + "." + form_field, "must retain one exact Unicode scalar")
            need(row.get(cp_field) == f"U+{ord(form):04X}", p, f + "." + cp_field, "must match exact Unicode scalar")
        need(row.get("id") not in pair_ids, p, f + ".id", "duplicate pair ID")
        pair_ids.add(row["id"])
        need(isinstance(row.get("categories"), list) and row["categories"], p, f + ".categories", "must retain source categories")
        need(isinstance(row.get("sourceOccurrences"), list) and row["sourceOccurrences"], p, f + ".sourceOccurrences", "must retain every deduplicated source position")
        need(row.get("source") in sources, p, f + ".source", "unknown source")
        need(row.get("reference") in refs and refs[row["reference"]]["source"] == row["source"], p, f + ".reference", "must bind the exact upstream module bytes")
        need(row.get("sourceStatus") == "candidate" and row.get("officialStatus") == "unverified", p, f, "do not promote source categories to official status")
    if written_forms["items"]:
        need(len(written_forms["items"]) == 452, root / "data" / "written-forms.yaml", "items", "pinned intake must retain all 452 exact pairs")
    joyo_ids: set[str] = set()
    joyo_source = "joyo-appendix-2010"
    joyo_reference = "joyo-appendix-2010-appendix"
    if joyo_readings["items"]:
        need(joyo_source in sources, root / "data" / "joyo-appendix.yaml", "source", "official Jōyō appendix source is missing from the registry")
        need(joyo_reference in refs and refs[joyo_reference]["source"] == joyo_source,
             root / "data" / "joyo-appendix.yaml", "reference", "official appendix reference is missing or belongs to another source")
        need("jmdict-e-2026-11-27" in sources and "jmdict-e-2026-11-27-spelling-reading" in refs
             and refs["jmdict-e-2026-11-27-spelling-reading"]["source"] == "jmdict-e-2026-11-27",
             root / "data" / "joyo-appendix.yaml", "entryIDs", "the pinned JMdict entry reference is missing from the registry")
    for i, row in enumerate(joyo_readings["items"]):
        p, f = root / "data" / "joyo-appendix.yaml", f"items[{i}]"
        exact_keys(row, {"id", "spelling", "reading", "sourceRow", "role", "entryIDs"}, p, f)
        nonempty(row.get("id"), p, f + ".id")
        need(row["id"] not in joyo_ids, p, f + ".id", "duplicate appendix reading ID")
        joyo_ids.add(row["id"])
        need(isinstance(row.get("spelling"), str) and row["spelling"] and all(is_scalar(ch) for ch in row["spelling"]),
             p, f + ".spelling", "must be a non-empty string of Unicode scalars")
        need(isinstance(row.get("reading"), str) and row["reading"] and all(is_scalar(ch) for ch in row["reading"]),
             p, f + ".reading", "must be a non-empty string of Unicode scalars")
        need(type(row.get("sourceRow")) is int and 1 <= row["sourceRow"] <= 116, p, f + ".sourceRow",
             "must identify a one-based appendix source-row ordinal")
        need(row.get("role") in {"primary", "alternate", "example"}, p, f + ".role", "unknown appendix listing role")
        need(isinstance(row.get("entryIDs"), list) and row["entryIDs"], p, f + ".entryIDs", "must link to exact JMdict entries")
        need(all(type(entry_id) is int and entry_id > 0 for entry_id in row["entryIDs"]), p, f + ".entryIDs",
             "JMdict entry IDs must be positive integers")
        need(len(row["entryIDs"]) == len(set(row["entryIDs"])), p, f + ".entryIDs", "duplicate JMdict entry ID")
    return (list(char_by_literal.values()), list(component_by_id.values()), list(structures_by_id.values()),
            radicals["items"], written_forms["items"], joyo_readings["items"])


def _intake(root: Path, references: dict[str, dict]) -> list[dict]:
    items = []
    for path in sorted((root / "intake").rglob("*.yaml")):
        doc = load(path)
        exact_keys(doc, {"version", "items"}, path)
        need(doc.get("version") == 1 and isinstance(doc.get("items"), list), path, "$", "requires version 1 and an items list")
        for i, row in enumerate(doc["items"]):
            field = f"items[{i}]"
            exact_keys(row, {"id", "kind", "subject", "references", "reason", "nextAction", "disposition", "publishable"}, path, field)
            nonempty(row.get("id"), path, field + ".id")
            nonempty(row.get("kind"), path, field + ".kind")
            need(isinstance(row.get("subject"), dict), path, field + ".subject", "must be typed")
            need(isinstance(row.get("references"), list), path, field + ".references", "must be a list")
            for ref in row["references"]:
                need(ref in references, path, field + ".references", f"unresolved reference {ref!r}")
            for key in ("reason", "nextAction", "disposition"):
                nonempty(row.get(key), path, field + "." + key)
            need(row.get("publishable") is False, path, field + ".publishable", "intake is never learner publishable")
            items.append(row)
    return items


def _imported_candidates(root: Path, sources: dict[str, dict], refs: dict[str, dict]) -> list[dict]:
    import json
    rows = []
    for path in sorted((root / "data" / "imports").rglob("*.jsonl")):
        with path.open(encoding="utf-8") as stream:
            for lineno, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                required = {"id", "kind", "subject", "payload", "source", "sourceRevision", "reference", "selector",
                            "sourceStatus", "japaneseApplicability", "reviewState", "publishable"}
                need(set(row) == required, path, f"line {lineno}", "must use the exact imported-candidate field set")
                nonempty(row.get("id"), path, f"line {lineno}.id")
                need(row["source"] in sources, path, f"line {lineno}.source", "unknown source")
                need(row["reference"] in refs and refs[row["reference"]]["source"] == row["source"], path,
                     f"line {lineno}.reference", "must identify an exact reference from the same source")
                for key in ("kind", "sourceRevision", "selector", "sourceStatus", "japaneseApplicability", "reviewState"):
                    nonempty(row.get(key), path, f"line {lineno}.{key}")
                need(isinstance(row.get("subject"), dict) and isinstance(row.get("payload"), dict), path,
                     f"line {lineno}", "subject and payload must be objects")
                need(row.get("publishable") is False, path, f"line {lineno}.publishable", "imported candidates stay outside publication until independently reviewed")
                rows.append(row)
    ids = [row["id"] for row in rows]
    need(len(ids) == len(set(ids)), root, "data/imports", "duplicate imported candidate ID")
    return rows


def _assets(root: Path, sources: dict[str, dict], refs: dict[str, dict]) -> list[dict]:
    path = root / "assets/assets.yaml"
    if not path.exists():
        return []
    from .validation import validate_url
    doc = load(path)
    exact_keys(doc, {"version", "items"}, path)
    need(doc.get("version") == 1 and isinstance(doc.get("items"), list), path, "$", "requires version 1 and an items list")
    rows = []
    ids: set[str] = set()
    files: set[str] = set()
    for i, row in enumerate(doc["items"]):
        field = f"items[{i}]"
        exact_keys(row, {"id", "kind", "subject", "path", "sha256", "source", "revision", "descriptionReference",
                         "mediaReference", "license", "licenseEvidenceURL", "attribution", "status", "reviewState",
                         "scriptLabel", "selector", "dateIsUploadDateOnly"}, path, field)
        nonempty(row.get("id"), path, field + ".id")
        need(row["id"] not in ids, path, field + ".id", "duplicate asset ID")
        ids.add(row["id"])
        need(row.get("kind") in {"historical-transcription", "historical-scan-crop", "educational-radical-illustration"}, path, field + ".kind", "unknown asset kind")
        need(isinstance(row.get("subject"), str) and len(row["subject"]) == 1, path, field + ".subject", "must be one exact Unicode scalar")
        nonempty(row.get("path"), path, field + ".path")
        need(row["path"] not in files, path, field + ".path", "duplicate asset path")
        files.add(row["path"])
        need(re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))) is not None, path, field + ".sha256", "must be a lowercase SHA-256")
        need(row.get("source") in sources, path, field + ".source", "unknown source")
        for key in ("revision", "attribution", "status", "reviewState", "selector", "scriptLabel"):
            nonempty(row.get(key), path, field + "." + key)
        validate_url(row.get("licenseEvidenceURL"), path, field + ".licenseEvidenceURL")
        need(row.get("license") in {"CC-BY", "CC-BY-SA", "CC0", "LicenseRef-ACC-Public-Domain-with-Fallback", "Public-Domain"}, path,
             field + ".license", "unknown or excluded asset license")
        need(row["license"] == sources[row["source"]]["license"], path, field + ".license",
             "unknown or excluded asset license for the scoped upstream grant")
        for ref_key in ("descriptionReference", "mediaReference"):
            ref_id = row.get(ref_key)
            need(ref_id in refs and refs[ref_id]["source"] == row["source"], path, field + "." + ref_key,
                 "must resolve to this asset source")
        media = refs[row["mediaReference"]]
        if row["source"] == "kanji-alive-radical-media":
            member_hash = re.search(r"(?:^|;\s*)memberSHA256=([0-9a-f]{64})(?:;|$)", row["selector"])
            need(member_hash is not None and member_hash.group(1) == row["sha256"], path, field + ".selector",
                 "the selected archive member hash must match the local asset bytes")
        else:
            need(row["sha256"] == media["snapshotHash"], path, field + ".mediaReference",
                 "the media reference snapshot hash must match the local asset bytes")
        if row["source"] == "codh-tensho-v2-te00039":
            media_url = media["url"]
            need(media_url.startswith("https://codh.rois.ac.jp/tensho/book/TE00039/characters/") and
                 "_TE00039_" in row["selector"], path, field + ".mediaReference",
                 "the scope of this source covers only crops from TE00039")
        need(row.get("status") == "candidate" and row.get("reviewState") == "pending-distinct-asset-review", path,
             field, "asset source eligibility does not replace distinct asset review")
        need(isinstance(row.get("dateIsUploadDateOnly"), bool), path, field + ".dateIsUploadDateOnly", "must be a boolean")
        asset_path = root / row["path"]
        need(not asset_path.is_symlink() and asset_path.is_file(), path, field + ".path", "asset must be an in-repository regular file")
        need(asset_path.resolve(strict=True).is_relative_to(root), path, field + ".path", "asset path escapes the repository")
        need(hashlib.sha256(asset_path.read_bytes()).hexdigest() == row["sha256"], path, field + ".sha256", "asset bytes do not match the pinned hash")
        rows.append(row)
    return rows


def build(root: Path, output: Path) -> str:
    claims, sources, refs = load_project(root)
    imported = _imports(root, sources)
    validate(root, preloaded=(claims, sources, refs, imported))
    chars, components, structures, radicals, written_forms, joyo_readings = imported
    intake = _intake(root, refs)
    imported_candidates = _imported_candidates(root, sources, refs)
    assets = _assets(root, sources, refs)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".kanji-build-", suffix=".sqlite", dir=output.parent)
    os.close(fd)
    try:
        conn = sqlite3.connect(temporary)
        try:
            conn.executescript(DDL)
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            conn.execute("INSERT INTO metadata VALUES (?,?)", ("schemaVersion", str(SCHEMA_VERSION)))
            conn.execute("INSERT INTO metadata VALUES (?,?)", ("inputManifest", _json(input_manifest(root))))
            for sid, source in sorted(sources.items()):
                conn.execute("INSERT INTO source VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    sid, source["author"], source["project"], source["url"], source["license"], source["licenseVersion"], source["licenseEvidenceURL"],
                    source["scope"], source["attribution"], source["modifications"], source["sourceLanguage"],
                    _json(source["upstream"]), source["revision"], source.get("sha256"), source["acquisitionMethod"], source["retrievedAt"],
                ))
            for rid, ref in sorted(refs.items()):
                conn.execute("INSERT INTO reference VALUES (?,?,?,?,?,?,?,?,?)", (
                    rid, ref["source"], ref["url"], ref["externalId"], ref["locator"], ref["revision"], ref["snapshotHash"],
                    ref["retrievedAt"], _json(ref["supports"]),
                ))
            for item in chars:
                conn.execute("INSERT INTO character VALUES (?,?,?,?,?)", (item["literal"], item["codepoint"], item["source"], item["revision"], item["reference"]))
            for item in components:
                conn.execute("INSERT INTO component VALUES (?,?,?,?,?,?)", (item["id"], item["form"], item["kind"], item["source"], item["revision"], item["reference"]))
            for item in structures:
                conn.execute("INSERT INTO structure VALUES (?,?,?,?,?,?,?)", (
                    item["id"], item["literal"], item["source"], item["revision"], item["selector"], item["variant"], item["reference"],
                ))
                for occ in item["occurrences"]:
                    conn.execute("INSERT INTO occurrence VALUES (?,?,?,?,?,?,?,?,?)", (
                        item["id"], occ["id"], occ["component"], occ["parent"], occ["ordinal"], occ["group"],
                        _json(occ["strokeIDs"]), occ["form"], _json(occ["attributes"]),
                    ))
            for item in radicals:
                conn.execute("INSERT INTO radical_name VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    item["id"], item["literal"], item["codepoint"], item.get("kangxiNumber"), item.get("englishMeaning"),
                    item.get("readingKana"), item.get("readingRomanized"), item.get("positionJapanese"), item.get("positionRomanized"),
                    item.get("importance"), item.get("origin"), item.get("variantOf"), item.get("variantOfId"), item["source"],
                    item["revision"], item["reference"], item["idsReference"], item["sourceRow"], item["sourceStatus"],
                    item["japaneseApplicability"],
                ))
            for item in written_forms:
                conn.execute("INSERT INTO written_form_pair VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    item["id"], item["newForm"], item["newCodepoint"], item["oldForm"], item["oldCodepoint"],
                    _json(item["categories"]), _json(item["sourceOccurrences"]), item["source"], item["revision"],
                    item["reference"], item["sourceStatus"], item["officialStatus"], int(item["newStructureAvailable"]),
                    int(item["oldStructureAvailable"]),
                ))
            for item in joyo_readings:
                source_id = "joyo-appendix-2010"
                reference_id = "joyo-appendix-2010-appendix"
                conn.execute("INSERT INTO joyo_appendix_reading VALUES (?,?,?,?,?,?,?,?)", (
                    item["id"], item["spelling"], item["reading"], item["sourceRow"], item["role"],
                    source_id, sources[source_id]["revision"], reference_id,
                ))
                for entry_id in item["entryIDs"]:
                    conn.execute("INSERT INTO joyo_appendix_jmdict_entry VALUES (?,?,?)", (
                        item["id"], entry_id, "jmdict-e-2026-11-27-spelling-reading",
                    ))
            for item in intake:
                conn.execute("INSERT INTO intake VALUES (?,?,?,?,?,?,?,?)", (
                    item["id"], item["kind"], _json(item["subject"]), _json(item["references"]),
                    item["reason"], item["nextAction"], item["disposition"], int(item["publishable"]),
                ))
            for item in imported_candidates:
                conn.execute("INSERT INTO imported_candidate VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                    item["id"], item["kind"], _json(item["subject"]), _json(item["payload"]), item["source"],
                    item["sourceRevision"], item["reference"], item["selector"], item["sourceStatus"],
                    item["japaneseApplicability"], item["reviewState"], int(item["publishable"]),
                ))
            for item in imported_candidates:
                payload = item["payload"]
                relation_rows = []
                if item["kind"] == "kanjium-phonetic-membership":
                    relation_rows.append(("phonetic-family-membership", payload.get("phoneticComponent"),
                                          payload.get("character"), None, None))
                elif item["kind"] == "kanjium-phonetic-family":
                    relation_rows.append(("phonetic-family-summary", payload.get("component"), None, None,
                                          payload.get("readingCandidate")))
                elif item["kind"] == "kanji-db-phonetic-series":
                    relation_rows.append(("phonetic-series-candidate", payload.get("component"),
                                          payload.get("kanji"), None, payload.get("reading")))
                elif item["kind"] == "kanji-db-similar-kanji":
                    relation_rows.append(("visual-similarity-candidate", None, payload.get("kanji"),
                                          payload.get("similar"), None))
                elif item["kind"] == "kanji-db-unlisted-variants":
                    relation_rows.append(("unlisted-variant-candidate", None, payload.get("unlisted"),
                                          payload.get("listed"), None))
                elif item["kind"] in {"kanji-db-kunyomi-groups", "kanji-db-homophone-groups"}:
                    relation_rows.append((item["kind"], None, None, None, payload.get("reading")))
                for ordinal, (kind, component_form, character_literal, related_literal, reading) in enumerate(relation_rows):
                    conn.execute("INSERT INTO candidate_relation VALUES (?,?,?,?,?,?,?,?)", (
                        item["id"], ordinal, kind, component_form, character_literal, related_literal, reading,
                        _json(payload),
                    ))
            for item in assets:
                conn.execute("INSERT INTO asset VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    item["id"], item["kind"], item["subject"], item["path"], item["sha256"], item["source"], item["revision"],
                    item["descriptionReference"], item["mediaReference"], item["license"], item["licenseEvidenceURL"],
                    item["attribution"], item["status"], item["reviewState"], item["scriptLabel"], item["selector"],
                    int(item["dateIsUploadDateOnly"]),
                ))
            for claim in claims:
                review = claim["review"]
                subject = claim["subject"]
                subject_id = subject.get("id") or subject.get("literal") or subject["occurrence"]
                conn.execute("INSERT INTO claim VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    claim["id"], claim["kind"], subject["type"], subject_id, subject.get("structure"),
                    subject.get("literal"), subject.get("codepoint"),
                    claim["revision"], claim["status"], claim["targetLanguage"],
                    claim["author"]["name"], claim["license"], review["state"], review.get("reviewer"),
                    review.get("reviewedAt"), review.get("claimRevision"), review.get("sourceRevision"), review.get("rationale"),
                ))
                for evidence in claim["evidence"]:
                    conn.execute("INSERT INTO claim_evidence VALUES (?,?,?,?,?)", (
                        claim["id"], evidence["reference"], evidence["claimField"], evidence["supportType"], evidence["selector"],
                    ))
                if claim["kind"] == "mnemonic":
                    story = claim["story"]
                    conn.execute("INSERT INTO story VALUES (?,?,?,?,?,?)", (
                        claim["id"], story["targetReference"], story["targetSelector"], story["originality"], 1, story["textRevision"],
                    ))
                    for ordinal, occurrence in enumerate(story["occurrences"]):
                        conn.execute("INSERT INTO story_occurrence VALUES (?,?,?,?,?,?,?)", (
                            claim["id"], ordinal, occurrence["structure"], occurrence["occurrence"], occurrence["labelClaim"],
                            occurrence["authoredForm"], _json(occurrence["crosswalk"]) if occurrence["crosswalk"] else None,
                        ))
                translation = claim.get("translationOf") or {}
                locale = claim.get("locale")
                text_revision = claim["localizedRevision"]
                conn.execute("INSERT INTO localized_text VALUES (?,?,?,?,?,?,?,?)", (
                    claim["id"], locale, text_revision, claim["claimText"], translation.get("claim"), translation.get("locale"),
                    translation.get("textRevision"), int(claim.get("status") == "stale"),
                ))
            conn.commit()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            need(integrity == "ok", output, "sqlite.integrity_check", integrity)
            need(not conn.execute("PRAGMA foreign_key_check").fetchall(), output, "sqlite.foreign_key_check", "failed")
            conn.execute("PRAGMA journal_mode=DELETE")
            conn.execute("VACUUM")
        finally:
            conn.close()
        os.replace(temporary, output)
    except Exception:
        # Preserve failed build evidence; the unique temporary file is intentionally not deleted.
        raise
    return hashlib.sha256(output.read_bytes()).hexdigest()
