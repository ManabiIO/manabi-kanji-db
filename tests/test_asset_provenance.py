from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

import yaml

from kanjidb.database import _assets
from kanjidb.validation import ValidationError


class AssetProvenanceTests(unittest.TestCase):
    def run_asset_validation(self, source: str, selector: str, media_hash: str, expected_error: str) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            asset_dir = root / "assets"
            asset_dir.mkdir()
            asset_bytes = b"locally pinned asset"
            (asset_dir / "asset.svg").write_bytes(asset_bytes)
            asset_hash = hashlib.sha256(asset_bytes).hexdigest()
            item = {
                "id": "test-asset", "kind": "historical-transcription", "subject": "山",
                "path": "assets/asset.svg", "sha256": asset_hash, "source": source,
                "revision": "rev-1", "descriptionReference": "description",
                "mediaReference": "media", "license": "CC-BY-SA",
                "licenseEvidenceURL": "https://example.test/license", "attribution": "Example",
                "status": "candidate", "reviewState": "pending-distinct-asset-review",
                "scriptLabel": "Test image of 山", "selector": selector, "dateIsUploadDateOnly": False,
            }
            (asset_dir / "assets.yaml").write_text(yaml.safe_dump({"version": 1, "items": [item]}))
            sources = {source: {"license": "CC-BY-SA"}}
            refs = {
                "description": {"source": source, "url": "https://example.test/description"},
                "media": {"source": source, "url": "https://example.test/media", "snapshotHash": media_hash},
            }
            with self.assertRaisesRegex(ValidationError, expected_error):
                _assets(root, sources, refs)

    def test_local_asset_bytes_must_match_media_reference_hash(self) -> None:
        self.run_asset_validation(
            "commons-test", "pageRevision=1", "0" * 64, "media reference snapshot hash must match",
        )

    def test_archive_member_hash_must_match_local_asset_bytes(self) -> None:
        self.run_asset_validation(
            "kanji-alive-radical-media", "archive-member=radical.svg; memberSHA256=" + "0" * 64, "a" * 64,
            "archive member hash must match",
        )


if __name__ == "__main__":
    unittest.main()
