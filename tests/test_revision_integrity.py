from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from kanjidb.validation import (
    REVIEWED_REVISIONS,
    ValidationError,
    _validate_claim_graph,
    claim_review_fingerprint,
    load_reviewed_fingerprints,
    validate_claim,
)


class RevisionIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.root = Path(workspace.name)
        (self.root / REVIEWED_REVISIONS.parent).mkdir()
        self.refs = {"ref": {"source": "kanjivg-test", "revision": "1", "snapshotHash": "a" * 64, "locator": "old"}}
        self.character = {"type": "character", "literal": "泳", "codepoint": "U+6CF3"}
        self.component = {"type": "component", "id": "cmp-water"}
        self.occurrence = {"id": "g1", "component": "cmp-water", "form": "氵", "attributes": {"original": "水"}}
        self.structure = {"id": "structure", "literal": "泳", "source": "kanjivg-test", "reference": "ref",
                          "occurrences": [self.occurrence]}
        self.imported = ([self.character], [self.component], [self.structure])
        self.label = self.claim("label", self.component, "visual-name")
        self.story = self.claim("story", self.character, "mnemonic")
        self.story["evidence"][0]["claimField"] = "story.targetReference"
        self.story["story"] = {
            "locale": "en", "originality": "original", "targetReference": "ref", "targetSelector": "selector",
            "occurrences": [{
                "structure": "structure", "occurrence": "g1", "labelClaim": "label", "authoredForm": "水",
                "crosswalk": {"fromCodepoint": "U+6C35", "toCodepoint": "U+6C34", "sourceAttribute": "original", "reference": "ref"},
            }], "fiction": True, "textRevision": "text-v1",
        }

    def claim(self, cid: str, subject: dict, kind: str, locale: str = "en") -> dict:
        return {
            "id": cid, "subject": copy.deepcopy(subject), "kind": kind, "locale": locale, "targetLanguage": "ja",
            "status": "approved", "revision": "claim-v1", "localizedRevision": "text-v1", "claimText": "Reviewed text",
            "author": {"name": "Author", "type": "human", "recordedAt": "2026-11-27"}, "license": "CC-BY-SA-4.0",
            "evidence": [{"reference": "ref", "claimField": "claimText", "supportType": "example", "selector": "selector"}],
            "review": {"state": "approved", "reviewer": "Reviewer", "reviewedAt": "2026-11-27",
                       "claimRevision": "claim-v1", "sourceRevision": "kanjivg-test:1:" + "a" * 64, "rationale": "Reviewed."},
        }

    def pin(self, *claims: dict) -> None:
        by_id = {claim["id"]: claim for claim in claims}
        structures = {"structure": self.structure}
        fingerprints = load_reviewed_fingerprints(self.root)
        for cid, claim in by_id.items():
            fingerprints[cid] = claim_review_fingerprint(claim, by_id, self.refs, structures)
        lines = ["version: 1", "revisions:"]
        for cid, fingerprint in sorted(fingerprints.items()):
            lines.append(f"  {cid}: {fingerprint}")
        (self.root / REVIEWED_REVISIONS).write_text("\n".join(lines) + "\n", encoding="utf-8")

    def validate_graph(self, *claims: dict) -> None:
        for claim in claims:
            validate_claim(claim, self.root / f"{claim['id']}.yaml", self.refs)
        _validate_claim_graph(self.root, list(claims), self.refs, self.imported, [])

    def test_approved_text_evidence_and_reference_must_match_reviewed_content(self) -> None:
        self.pin(self.label)
        self.validate_graph(self.label)
        for field in ("claimText", "evidence"):
            with self.subTest(field=field):
                claim = copy.deepcopy(self.label)
                if field == "claimText":
                    claim[field] = "Edited wording"
                else:
                    claim[field][0]["selector"] = "edited selector"
                with self.assertRaisesRegex(ValidationError, "review.label.*matching reviewed fingerprint"):
                    self.validate_graph(claim)
        self.refs["ref"]["locator"] = "edited locator"
        with self.assertRaisesRegex(ValidationError, "review.label.*matching reviewed fingerprint"):
            self.validate_graph(self.label)

    def test_reapproval_of_a_renamed_label_requires_story_review(self) -> None:
        self.pin(self.story, self.label)
        self.validate_graph(self.story, self.label)
        self.label["claimText"] = "Changed cue"
        self.pin(self.label)
        with self.assertRaisesRegex(ValidationError, "review.story.*matching reviewed fingerprint"):
            self.validate_graph(self.story, self.label)
        self.label["status"] = "stale"
        with self.assertRaisesRegex(ValidationError, "approved story requires a currently approved label"):
            self.validate_graph(self.story, self.label)

    def test_approved_story_selector_must_match_reviewed_selector(self) -> None:
        self.pin(self.story, self.label)
        self.story["story"]["targetSelector"] = "different target selector"
        self.story["evidence"][0]["selector"] = "different target selector"
        with self.assertRaisesRegex(ValidationError, "review.story.*matching reviewed fingerprint"):
            self.validate_graph(self.story, self.label)

    def test_crosswalk_uses_the_bound_occurrences_original_form(self) -> None:
        self.story["status"] = self.label["status"] = "stale"
        self.validate_graph(self.story, self.label)
        binding = self.story["story"]["occurrences"][0]
        binding["authoredForm"] = "火"
        binding["crosswalk"]["toCodepoint"] = "U+706B"
        with self.assertRaisesRegex(ValidationError, "recorded original attribute"):
            self.validate_graph(self.story, self.label)

    def test_orphan_subjects_cannot_be_authored_claims(self) -> None:
        for subject in ({"type": "character", "literal": "火", "codepoint": "U+706B"},
                        {"type": "component", "id": "missing"},
                        {"type": "occurrence", "structure": "structure", "occurrence": "missing"},
                        {"type": "asset", "id": "missing"}):
            with self.subTest(subject=subject):
                claim = self.claim("orphan", subject, "visual-name")
                claim["status"] = "candidate"
                with self.assertRaisesRegex(ValidationError, f"unknown {subject['type']} subject"):
                    self.validate_graph(claim)

    def test_translation_rejects_wrong_source_locale_and_cycles(self) -> None:
        en = self.label
        fr = self.claim("label-fr", self.component, "visual-name", "fr")
        en["status"] = fr["status"] = "stale"
        fr["translationOf"] = {"claim": "label", "locale": "es", "textRevision": "text-v1"}
        with self.assertRaisesRegex(ValidationError, "match the source claim locale"):
            self.validate_graph(en, fr)
        fr["translationOf"]["locale"] = "en"
        en["translationOf"] = {"claim": "label-fr", "locale": "fr", "textRevision": "text-v1"}
        with self.assertRaisesRegex(ValidationError, "translation cycle"):
            self.validate_graph(en, fr)

    def test_translation_review_binds_source_text_and_stale_history_can_be_stored(self) -> None:
        fr = self.claim("label-fr", self.component, "visual-name", "fr")
        fr["translationOf"] = {"claim": "label", "locale": "en", "textRevision": "text-v1"}
        self.pin(self.label, fr)
        self.validate_graph(self.label, fr)
        self.label["claimText"] = "Changed source text with the old revision label"
        with self.assertRaisesRegex(ValidationError, "review.label-fr.*matching reviewed fingerprint"):
            self.validate_graph(fr, self.label)
        fr["status"] = self.label["status"] = "stale"
        self.label["revision"] = "claim-v2"
        self.label["localizedRevision"] = "text-v2"
        self.validate_graph(self.label, fr)

    def test_status_approved_requires_a_current_approval(self) -> None:
        self.label["review"]["state"] = "pending"
        with self.assertRaisesRegex(ValidationError, "approved status requires an approved review"):
            self.validate_graph(self.label)
