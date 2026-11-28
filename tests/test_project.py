from __future__ import annotations

import copy
import sqlite3
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

import yaml

from kanjidb.database import _assets, _imported_candidates, build, input_files
from kanjidb.validation import ValidationError, load_project, validate, validate_claim
from kanjidb.yamlio import loads

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_story_seed import exact_sense
from story_labels import component_label
from audit_component_coverage import reviewed_label_disposition


class StrictYamlTests(unittest.TestCase):
    def test_rejects_duplicate_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate key"):
            loads("name: first\nname: second\n")

    def test_rejects_aliases_and_merge_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "aliases are not allowed"):
            loads("defaults: &defaults {a: 1}\ncopy: *defaults\n")
        with self.assertRaisesRegex(ValueError, "merge keys are not allowed"):
            loads("copy:\n  <<: {a: 1}\n")

    def test_rejects_non_string_mapping_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "mapping keys must be strings"):
            loads("1: numeric key\n")


class ProjectValidationTests(unittest.TestCase):
    def test_project_validates_with_reviewed_story_content(self) -> None:
        claims, sources, references = validate(ROOT)
        self.assertGreaterEqual(claims, 709)
        self.assertGreaterEqual(sources, 17)
        self.assertGreaterEqual(references, 6682)
        manifest = yaml.safe_load((ROOT / "data/story-seed-manifest.yaml").read_text())
        self.assertEqual(manifest["reviewDisposition"]["approvedStoryCount"], 150)
        self.assertEqual(manifest["reviewDisposition"]["approvedVisualNameCount"], 141)
        self.assertEqual(len(manifest["claims"]), 291)

    def test_donor_vocabulary_manifest_accounts_for_bound_and_withheld_examples(self) -> None:
        manifest = yaml.safe_load((ROOT / "data/coverage/donor-v26-reading-examples.yaml").read_text())
        self.assertEqual(manifest["counts"], {"donorExamples": 100, "boundExamples": 98, "withheldExamples": 2})
        self.assertEqual(len(manifest["items"]), 100)
        self.assertEqual(sum("claim" in item for item in manifest["items"]), 98)
        self.assertEqual(sum("intake" in item for item in manifest["items"]), 2)

    def test_donor_claim_review_manifest_matches_fingerprint_ledger(self) -> None:
        manifest = yaml.safe_load((ROOT / "data/coverage/donor-claim-review.yaml").read_text())
        revisions = yaml.safe_load((ROOT / "data/reviewed-claim-revisions.yaml").read_text())["revisions"]
        approved = manifest["approvedClaims"]
        self.assertEqual(manifest["counts"], {"reviewedCandidates": 192, "approved": 181, "heldForRevision": 11})
        self.assertEqual(len(approved), len(set(approved)))
        self.assertTrue(set(approved) <= revisions.keys())
        self.assertEqual(len(manifest["holds"]), 11)

    def test_upstream_source_snapshots_are_excluded_from_build_inputs(self) -> None:
        paths = input_files(ROOT)
        self.assertFalse(any("source-files" in path.parts for path in paths))

    def test_reviewed_stories_and_linked_labels_reach_the_learner_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "learner-view.sqlite"
            build(ROOT, database)
            with closing(sqlite3.connect(database)) as db:
                story_count = db.execute("SELECT count(*) FROM current_approved_claim WHERE kind='mnemonic'").fetchone()[0]
                label_count = db.execute("SELECT count(*) FROM current_approved_claim WHERE kind='visual-name'").fetchone()[0]
                reading_example_count = db.execute("SELECT count(*) FROM current_approved_claim WHERE kind='reading-example'").fetchone()[0]
                linked_count = db.execute("""
                    SELECT count(*) FROM story_occurrence occurrence
                    JOIN current_approved_claim story ON story.id=occurrence.claim_id
                    JOIN current_approved_claim label ON label.id=occurrence.label_claim_id
                    WHERE story.kind='mnemonic' AND label.kind='visual-name'
                """).fetchone()[0]
                pending_claim_id = db.execute("""
                    SELECT id FROM claim
                    WHERE kind='visual-name' AND (status='candidate' OR review_state!='approved') LIMIT 1
                """).fetchone()[0]
                pending_claim_public_count = db.execute(
                    "SELECT count(*) FROM current_approved_claim WHERE id=?", (pending_claim_id,)
                ).fetchone()[0]
                seed_manifest = yaml.safe_load((ROOT / "data/story-seed-manifest.yaml").read_text())
                seed_claim_ids = {row["id"] for row in seed_manifest["claims"]}
                approved_claim_ids = {row[0] for row in db.execute("SELECT id FROM current_approved_claim")}
                phonetic_roles = db.execute("""
                    SELECT character_literal, structure_id, occurrence_id, role_kind, claim_id
                    FROM approved_component_role
                    WHERE visible_form='青' AND role_kind='historical-phonetic'
                    ORDER BY character_literal
                """).fetchall()
                visible_members = db.execute("""
                    SELECT count(DISTINCT literal) FROM visible_component_occurrence WHERE visible_form='青'
                """).fetchone()[0]
                functional_characters = db.execute("""
                    SELECT count(DISTINCT character_literal)
                    FROM approved_component_role WHERE visible_form='青'
                """).fetchone()[0]
                role_query_plan = db.execute("""
                    EXPLAIN QUERY PLAN SELECT character_literal FROM approved_component_role
                    WHERE visible_form='青' AND role_kind='historical-phonetic'
                """).fetchall()
                expected_role_ids = {row[0] for row in db.execute("""
                    SELECT id FROM current_approved_claim
                    WHERE subject_type='occurrence'
                      AND kind IN ('semantic-function', 'historical-phonetic', 'modern-japanese-sound')
                """)}
                actual_role_ids = {row[0] for row in db.execute("SELECT claim_id FROM approved_component_role")}
                component_label_review = reviewed_label_disposition(
                    db, json.loads((ROOT / "data/coverage/component-label-review.json").read_text())
                )
            self.assertGreaterEqual(story_count, 150)
            self.assertEqual(label_count, 205)
            self.assertGreaterEqual(reading_example_count, 98)
            self.assertGreaterEqual(linked_count, 300)
            self.assertEqual(pending_claim_public_count, 0)
            self.assertTrue(seed_claim_ids <= approved_claim_ids)
            self.assertEqual(phonetic_roles, [(
                "清", "kv-6e05", "kvg:06e05-g2", "historical-phonetic", "historical-phonetic-u6e05-u9752"
            )])
            self.assertGreater(visible_members, functional_characters)
            self.assertEqual(functional_characters, 5)
            self.assertEqual(actual_role_ids, expected_role_ids)
            self.assertTrue(any("occurrence_visible_form_lookup" in row[3] for row in role_query_plan), role_query_plan)
            self.assertEqual(component_label_review["approvedLabels"], 64)
            self.assertEqual(component_label_review["withheld"][0]["form"], "CDP-8CB8")
            self.assertEqual(component_label_review["withheld"][0]["sourceGroups"], ["kvg:06b66-g1", "kvg:06b66-g6"])

    def test_approved_claim_review_must_bind_exact_revision(self) -> None:
        claims, _, refs = load_project(ROOT)
        claim = copy.deepcopy(next(row for row in claims if row["kind"] == "mnemonic"))
        claim["review"]["claimRevision"] = "0" * 64
        with self.assertRaisesRegex(ValidationError, "approved review must bind the current claim revision"):
            validate_claim(claim, ROOT / "test-claim.yaml", refs)

    def test_source_import_candidates_cannot_be_publishable(self) -> None:
        claims, sources, refs = load_project(ROOT)
        del claims
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "data/imports"
            target.mkdir(parents=True)
            source = next((ROOT / "data/imports").rglob("*.jsonl"))
            row = json.loads(source.read_text().splitlines()[0])
            row["publishable"] = True
            (target / "candidate.jsonl").write_text(json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValidationError, "imported candidates stay outside publication"):
                _imported_candidates(root, sources, refs)

    def test_assets_remain_pending_and_hash_pinned(self) -> None:
        _, sources, refs = load_project(ROOT)
        assets = yaml.safe_load((ROOT / "assets/assets.yaml").read_text())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(strict=True)
            shutil.copytree(ROOT / "assets", root / "assets")
            document = yaml.safe_load((root / "assets/assets.yaml").read_text())
            document["items"][0]["license"] = "CC-BY-SA"
            (root / "assets/assets.yaml").write_text(yaml.safe_dump(document, allow_unicode=True))
            with self.assertRaisesRegex(ValidationError, "unknown or excluded asset license"):
                _assets(root, sources, refs)
            codh = next(item for item in document["items"] if item["source"] == "codh-tensho-v2-te00039")
            document["items"][0]["license"] = assets["items"][0]["license"]
            codh["selector"] = codh["selector"].replace("TE00039", "TE00041")
            (root / "assets/assets.yaml").write_text(yaml.safe_dump(document, allow_unicode=True))
            with self.assertRaisesRegex(ValidationError, "only crops from TE00039"):
                _assets(root, sources, refs)
        self.assertEqual(len(assets["items"]), 25)

    def test_exact_target_selector_uses_requested_ordinary_sense(self) -> None:
        senses = [[(1, 1, "day"), (1, 2, "day of the week")]]
        self.assertEqual(exact_sense(senses, "day of the week"), (1, 2))

    def test_month_and_flesh_story_cues_follow_japanese_context(self) -> None:
        self.assertEqual(component_label("月", "月", "月", {}), "moon")
        self.assertEqual(component_label("月", "月", "肩", {"original": "肉"}), "flesh")

    def test_repeated_and_split_component_occurrences_are_distinct(self) -> None:
        claims, _, _ = load_project(ROOT)
        stories = [claim for claim in claims if claim["kind"] == "mnemonic"]
        repeated = next(claim for claim in stories if claim["subject"]["literal"] == "林")
        refs = [binding["occurrence"] for binding in repeated["story"]["occurrences"]]
        self.assertEqual(len(refs), len(set(refs)))
        split = next(claim for claim in stories if any(binding["crosswalk"] for binding in claim["story"]["occurrences"]))
        self.assertTrue(any(binding["crosswalk"] for binding in split["story"]["occurrences"]))


if __name__ == "__main__":
    unittest.main()
