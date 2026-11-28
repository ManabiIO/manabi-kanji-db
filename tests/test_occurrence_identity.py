from __future__ import annotations

import copy
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import yaml

from kanjidb.database import build
from kanjidb.release import release_manifest
from kanjidb.validation import REVIEWED_REVISIONS, claim_review_fingerprint, source_revision


class OccurrenceIdentityTests(unittest.TestCase):
    def test_snapshot_preserves_structure_scope_of_occurrence_claims(self) -> None:
        url = "https://example.org/fixture"
        timestamp = "2026-01-01T00:00:00Z"
        source = {
            "id": "fixture", "author": "Fixture author", "project": "Fixture project",
            "url": url, "license": "CC0", "licenseVersion": "1.0", "licenseEvidenceURL": url,
            "scope": "Test glyphs", "attribution": "Fixture author", "modifications": "None",
            "sourceLanguage": "ja", "upstream": [], "revision": "rev-1",
            "acquisitionMethod": "Test fixture", "retrievedAt": timestamp,
        }
        ref = {
            "id": "fixture-ref", "source": source["id"], "url": url, "externalId": "test-glyph",
            "locator": "fixture", "revision": source["revision"], "snapshotHash": "a" * 64,
            "retrievedAt": timestamp, "supports": ["structure"],
        }
        provenance = {"source": source["id"], "revision": source["revision"], "reference": ref["id"]}
        character = {"literal": "泳", "codepoint": "U+6CF3"}
        component = {"id": "cmp-water", "form": "水", "kind": "encoded", **provenance}
        occurrence = {
            "id": "g1", "component": component["id"], "parent": None, "ordinal": 0,
            "group": "g1", "strokeIDs": ["s1"], "form": "氵", "sourceID": "g1", "attributes": {},
        }
        structures = {
            variant: {
                "id": variant, "literal": character["literal"], "variant": variant,
                "selector": variant, "occurrences": [copy.deepcopy(occurrence)], **provenance,
            }
            for variant in ("ja", "ja-alt")
        }
        evidence = [{"reference": ref["id"], "claimField": "claimText", "supportType": "example", "selector": "g1"}]
        refs = {ref["id"]: ref}
        claim = {
            "id": "water-role", "kind": "semantic-function", "subject": {
                "type": "occurrence", "structure": "ja-alt", "occurrence": occurrence["id"],
            },
            "revision": "claim-v1", "localizedRevision": "text-v1", "status": "approved",
            "claimText": "The water component contributes the sense of swimming.",
            "author": {"name": "Fixture author", "type": "human", "recordedAt": "2026-01-01"},
            "license": "CC-BY-SA-4.0", "evidence": evidence, "targetLanguage": "ja", "locale": "en",
            "review": {
                "state": "approved", "reviewer": "Fixture reviewer", "reviewedAt": "2026-01-01",
                "claimRevision": "claim-v1", "sourceRevision": source_revision(evidence, refs),
                "rationale": "Checked the exact structure and occurrence.",
            },
        }
        fingerprint = claim_review_fingerprint(claim, {claim["id"]: claim}, refs, structures)
        fixture_files = {
            "sources/registry.yaml": {"version": 1, "sources": [source], "references": [ref]},
            "sources/reuse-scopes.json": {},
            "data/characters.yaml": {"version": 1, "items": [{**character, "baseline": character, **provenance}]},
            "data/components.yaml": {"version": 1, "items": [component]},
            "data/structures.yaml": {"version": 1, "items": list(structures.values())},
            "content/water-role.yaml": claim,
            REVIEWED_REVISIONS: {"version": 1, "revisions": {claim["id"]: fingerprint}},
        }
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for relative_path, value in fixture_files.items():
                path = root / relative_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(yaml.safe_dump(value, allow_unicode=True), encoding="utf-8")
            database = root / "kanji.sqlite"
            build(root, database)

            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone(), (4,))
                self.assertEqual(connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schemaVersion'"
                ).fetchone(), ("4",))
                self.assertEqual(connection.execute(
                    "SELECT count(*) FROM occurrence WHERE occurrence_id = 'g1'"
                ).fetchone(), (2,))
                matches = connection.execute("""
                    SELECT c.id, o.structure_id, o.occurrence_id
                    FROM current_approved_claim AS c
                    JOIN occurrence AS o ON o.structure_id = c.subject_structure_id
                                        AND o.occurrence_id = c.subject_id
                    WHERE c.subject_type = 'occurrence'
                """).fetchall()
                self.assertEqual(matches, [("water-role", "ja-alt", "g1")])

                connection.execute("PRAGMA foreign_keys = ON")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE claim SET subject_structure_id = 'missing'")
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("UPDATE claim SET subject_structure_id = NULL")

            self.assertEqual(release_manifest(root, database)["databaseSchemaVersion"], 4)
