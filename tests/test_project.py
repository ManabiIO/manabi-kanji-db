from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from kanjidb.database import _assets, _imported_candidates, input_files
from kanjidb.validation import ValidationError, load_project, validate, validate_claim
from kanjidb.yamlio import loads

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from import_story_seed import exact_sense
from story_labels import component_label


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
        self.assertEqual(validate(ROOT), (413, 11, 6471))
        manifest = yaml.safe_load((ROOT / "data/story-seed-manifest.yaml").read_text())
        self.assertEqual(manifest["reviewDisposition"]["approvedStoryCount"], 150)
        self.assertEqual(manifest["reviewDisposition"]["approvedVisualNameCount"], 141)
        self.assertEqual(len(manifest["claims"]), 291)

    def test_upstream_source_snapshots_are_excluded_from_build_inputs(self) -> None:
        paths = input_files(ROOT)
        self.assertFalse(any("source-files" in path.parts for path in paths))

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
            root = Path(temp)
            shutil.copytree(ROOT / "assets", root / "assets")
            document = yaml.safe_load((root / "assets/assets.yaml").read_text())
            document["items"][0]["license"] = "CC-BY-SA"
            (root / "assets/assets.yaml").write_text(yaml.safe_dump(document, allow_unicode=True))
            with self.assertRaisesRegex(ValidationError, "unknown or excluded asset license"):
                _assets(root, sources, refs)
        self.assertEqual(len(assets["items"]), 21)

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
