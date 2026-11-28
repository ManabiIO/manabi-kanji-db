from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from copy import deepcopy
from contextlib import closing
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kanjidb.database import _load_joyo_appendix, _validate_joyo_appendix, build
from kanjidb.validation import ValidationError, validate_registry
from kanjidb.yamlio import load
from verify_joyo_jmdict import allowed_pairs


class JoyoAppendixTests(unittest.TestCase):
    def _assert_import_error(self, mutator, message: str) -> None:
        registry = load(ROOT / "sources" / "registry.yaml")
        sources, refs = validate_registry(registry, ROOT / "sources" / "registry.yaml")
        doc = deepcopy(load(ROOT / "data" / "joyo-appendix.yaml"))
        mutator(doc["items"])
        with self.assertRaisesRegex(ValidationError, message):
            _validate_joyo_appendix(ROOT, registry, sources, refs, doc)

    def test_jmdict_reading_pair_honors_restrictions_and_no_kanji(self) -> None:
        entry = ET.fromstring("""
            <entry>
              <k_ele><keb>五月</keb><keb>五月祭</keb></k_ele>
              <r_ele><reb>さつき</reb><re_restr>五月</re_restr></r_ele>
              <r_ele><reb>サツキ</reb><re_nokanji/></r_ele>
            </entry>
        """)
        self.assertEqual(allowed_pairs(entry), {("五月", "さつき")})

    def test_registered_appendix_cannot_silently_disappear(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            registry = load(ROOT / "sources" / "registry.yaml")
            sources, _ = validate_registry(registry, ROOT / "sources" / "registry.yaml")
            with self.assertRaisesRegex(ValidationError, "require the canonical appendix data file"):
                _load_joyo_appendix(root, sources)

    def test_registered_appendix_cannot_be_replaced_with_empty_items(self) -> None:
        self._assert_import_error(lambda rows: rows.clear(), "requires its reviewed canonical rows")

    def test_malformed_id_is_rejected_with_field_context(self) -> None:
        self._assert_import_error(lambda rows: rows[0].update(id="joyo appendix"), r"items\[0\]\.id: must use")

    def test_whitespace_only_spelling_is_rejected(self) -> None:
        self._assert_import_error(lambda rows: rows[0].update(spelling=" 　"), r"items\[0\]\.spelling: must not contain whitespace")

    def test_non_hiragana_reading_is_rejected(self) -> None:
        self._assert_import_error(lambda rows: rows[0].update(reading="あす1"), r"items\[0\]\.reading: must contain only hiragana")

    def test_duplicate_spelling_reading_pair_is_rejected(self) -> None:
        self._assert_import_error(
            lambda rows: rows[1].update(spelling=rows[0]["spelling"], reading=rows[0]["reading"]),
            "duplicate appendix spelling/reading pair",
        )

    def test_noncanonical_jmdict_links_fail_offline_fingerprint(self) -> None:
        self._assert_import_error(
            lambda rows: rows[0].update(entryIDs=[99999999]),
            "independently reviewed canonical material",
        )

    def test_semantic_fingerprint_allows_yaml_formatting_changes(self) -> None:
        registry = load(ROOT / "sources" / "registry.yaml")
        sources, refs = validate_registry(registry, ROOT / "sources" / "registry.yaml")
        original = load(ROOT / "data" / "joyo-appendix.yaml")
        reformatted = yaml.safe_load(yaml.safe_dump(original, allow_unicode=True, sort_keys=False))
        self.assertEqual(len(_validate_joyo_appendix(ROOT, registry, sources, refs, reformatted)), 126)

    def test_joyo_rows_and_exact_jmdict_entry_links_reach_query_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "joyo.sqlite"
            build(ROOT, database)
            with closing(sqlite3.connect(database)) as db:
                counts = dict(db.execute("SELECT role, count(*) FROM joyo_appendix_reading GROUP BY role"))
                self.assertEqual(counts, {"alternate": 1, "example": 2, "primary": 123})
                self.assertEqual(db.execute("SELECT count(*) FROM joyo_appendix_jmdict_entry").fetchone()[0], 126)
                self.assertEqual(db.execute("SELECT count(*) FROM official_joyo_appendix_reading").fetchone()[0], 126)

                def entries(spelling: str, reading: str) -> list[int]:
                    return [row[0] for row in db.execute(
                        "SELECT jmdict_entry_id FROM official_joyo_appendix_reading "
                        "WHERE spelling=? AND reading=? ORDER BY jmdict_entry_id", (spelling, reading)
                    )]

                self.assertEqual(entries("明日", "あす"), [1584660])
                self.assertEqual(entries("海女", "あま"), [1201420])
                self.assertEqual(entries("海士", "あま"), [1772480])
                self.assertEqual(entries("投網", "とあみ"), [1447360])
                self.assertEqual(entries("師走", "しわす"), [1579500])
                self.assertEqual(len(entries("師走", "しはす")), 1)
                self.assertEqual(len(entries("魚河岸", "うおがし")), 1)
                self.assertEqual(len(entries("一言居士", "いちげんこじ")), 1)
                self.assertEqual(entries("五月", "さつき"), [1299600])
                self.assertEqual(entries("日本", "にほん"), [])

                def members(character: str) -> list[tuple[str, int]]:
                    return db.execute(
                        "SELECT r.spelling, c.spelling_offset "
                        "FROM joyo_appendix_character c "
                        "JOIN joyo_appendix_reading r ON r.id=c.reading_id "
                        "WHERE c.character_literal=? ORDER BY r.spelling, c.spelling_offset",
                        (character,),
                    ).fetchall()

                sun_memberships = members("日")
                self.assertIn(("一日", 1), sun_memberships)
                self.assertIn(("今日", 1), sun_memberships)
                self.assertIn(("明日", 1), sun_memberships)
                self.assertNotEqual(
                    [row for row in sun_memberships if row[0] == "一日"],
                    [row for row in sun_memberships if row[0] == "今日"],
                )
                self.assertEqual(
                    db.execute(
                        "SELECT c.character_literal, c.spelling_offset "
                        "FROM joyo_appendix_character c JOIN joyo_appendix_reading r ON r.id=c.reading_id "
                        "WHERE r.spelling='十重二十重' ORDER BY c.spelling_offset"
                    ).fetchall(),
                    [("十", 0), ("重", 1), ("二", 2), ("十", 3), ("重", 4)],
                )
                self.assertEqual(
                    db.execute(
                        "SELECT c.character_literal, c.spelling_offset "
                        "FROM joyo_appendix_character c JOIN joyo_appendix_reading r ON r.id=c.reading_id "
                        "WHERE r.spelling='差し支える' ORDER BY c.spelling_offset"
                    ).fetchall(),
                    [("差", 0), ("支", 2)],
                )
                plan = db.execute(
                    "EXPLAIN QUERY PLAN SELECT reading_id FROM joyo_appendix_character WHERE character_literal=?",
                    ("日",),
                ).fetchall()
                self.assertTrue(any("joyo_appendix_character_lookup" in row[3] for row in plan), plan)


if __name__ == "__main__":
    unittest.main()
