from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch

import yaml

from kanjidb.audit import audit


class FakeResponse:
    status = 200

    def __init__(self, body: bytes, content_type: str, final_url: str) -> None:
        self.body = body
        self.final_url = final_url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        return None

    def read(self, limit: int) -> bytes:
        return self.body

    def geturl(self) -> str:
        return self.final_url


class CitationAuditTests(unittest.TestCase):
    def run_audit(self, url: str, body: bytes, content_type: str, final_url: str) -> dict:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "queue.json"
            registry = {
                "version": 1,
                "sources": [{
                    "id": "test-source", "author": "Test", "project": "Test source",
                    "url": "https://example.test/", "license": "CC-BY-SA", "licenseVersion": "4.0",
                    "licenseEvidenceURL": "https://example.test/license", "scope": "test scope",
                    "attribution": "Test", "modifications": "None", "sourceLanguage": "en",
                    "upstream": [], "revision": "rev-1", "sha256": None,
                    "acquisitionMethod": "test fixture", "retrievedAt": "2026-11-27T00:00:00Z",
                }],
                "references": [{
                    "id": "test-reference", "source": "test-source", "url": url,
                    "externalId": "test", "locator": "exact test locator", "revision": "rev-1",
                    "snapshotHash": hashlib.sha256(body).hexdigest(), "retrievedAt": "2026-11-27T00:00:00Z",
                    "supports": ["test citation audit"],
                }],
            }
            (root / "sources").mkdir()
            (root / "sources/registry.yaml").write_text(yaml.safe_dump(registry, sort_keys=False))
            response = FakeResponse(body, content_type, final_url)
            with patch("kanjidb.audit.urllib.request.urlopen", return_value=response):
                audit(root, output, refresh=True, limit=1)
            return json.loads(output.read_text())["items"][0]

    def test_image_response_from_extensionless_endpoint_is_hash_checked(self) -> None:
        image = b"pinned image bytes"
        item = self.run_audit(
            "https://example.test/ShowImage.ashx?character=%E6%97%A5", image, "image/png",
            "https://example.test/ShowImage.ashx?character=%E6%97%A5",
        )
        self.assertEqual(item["result"], "retrieved-raw-snapshot")
        self.assertTrue(item["hashMatches"])
        self.assertEqual(item["finalURL"], "https://example.test/ShowImage.ashx?character=%E6%97%A5")
        self.assertEqual(item["contentType"], "image/png")

    def test_revision_page_audit_records_redirect_destination_without_claiming_hash_match(self) -> None:
        page = b"<html>current page</html>"
        item = self.run_audit(
            "https://example.test/wiki?oldid=17", page, "text/html",
            "https://example.test/wiki?oldid=18",
        )
        self.assertEqual(item["result"], "retrieved-revision-page")
        self.assertFalse(item["hashCompared"])
        self.assertEqual(item["finalURL"], "https://example.test/wiki?oldid=18")
        self.assertEqual(item["contentType"], "text/html")


if __name__ == "__main__":
    unittest.main()
