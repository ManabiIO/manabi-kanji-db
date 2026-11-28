from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from kanjidb.database import build
from verify_joyo_jmdict import allowed_pairs


class JoyoAppendixTests(unittest.TestCase):
    def test_jmdict_reading_pair_honors_restrictions_and_no_kanji(self) -> None:
        entry = ET.fromstring("""
            <entry>
              <k_ele><keb>五月</keb><keb>五月祭</keb></k_ele>
              <r_ele><reb>さつき</reb><re_restr>五月</re_restr></r_ele>
              <r_ele><reb>サツキ</reb><re_nokanji/></r_ele>
            </entry>
        """)
        self.assertEqual(allowed_pairs(entry), {("五月", "さつき")})

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


if __name__ == "__main__":
    unittest.main()
