# Imported source notices

Notices here apply only to the named material and do not license unrelated
fields or media. Each notice is retained beside a pinned source record in
`sources/registry.yaml`.

## Initial sources

- **KanjiVG** (`r20260714`): Ulrich Apel and contributors, CC BY-SA 3.0.
  Original notice: `KANJIVG-COPYING.txt`. Only Japanese stroke/group structure
  is imported; the complete KanjiVG drawings are not bundled in this project.
- **KANJIDIC2** (`2026-331`, file version 4): EDRDG and contributors, CC BY-SA
  4.0. Literal and codepoint provide the overlay join. Individual teaching
  claims cite exact selected sense or Japanese-reading fields; general reading
  and meaning lists are not copied.
- **Kanji Alive Japanese Radicals**: Kanji Alive, CC BY 4.0 for the radical
  language data. Radical names and variant relations are imported from the two
  pinned CSV files. Mnemonic hints, images, animation and font files are
  excluded from this license scope.
- **ManabiDictionaries editorial data v26**: project-authored explanatory data
  offered under CC BY-SA 4.0 in the donor's data distribution. Only eligible
  data fields are migrated. Missing public evidence remains in typed intake;
  the donor repository is not used as sole factual evidence.
- **Kanjium**: Kanjium contributors, CC BY-SA 4.0. The pinned import includes
  phonetic families and memberships, component structure, radical names, and
  compact meaning candidates. Reading and component suggestions remain
  unreviewed, and Kanjium lineage is not independent corroboration.
- **kanji-db.com data**: uball and contributors, CC BY-SA 4.0. The published
  relation tables are retained with upstream KANJIDIC2/JMdict/KanjiVG/IDS/
  Unihan lineage. Every row remains a candidate, not an approved Japanese cue.
- **Wikimedia Commons ACC assets**: only the 17 exact Sears-derived SVGs in
  `assets/historical-forms/` use the per-file public-domain dedication and
  fallback recorded in the preserved notice and permission file. 山-oracle.svg
  is Wargaz's separate public-domain transcription.
- **Kanji Alive drawings**: three modern teaching illustrations (山, 木, 貝)
  under CC BY 4.0. The exact attribution is in
  `KANJI-ALIVE-ANIMATIONS-NOTICE.md`; these are not historical forms. Hints,
  other graphics, and fonts are excluded.
- **JMdict and JmdictFurigana**: EDRDG and contributors, and Doublevil and
  contributors, CC BY-SA 4.0. Selected teaching examples cite exact spelling,
  reading, and per-character ruby alignment records. Bulk dictionaries and
  generator code are not included. See `VOCABULARY-EVIDENCE-NOTICE.md`.
- **CODH 篆書字体データセット v2**: one identified TE00039 seal-script crop
  under CC BY-SA 4.0. Its original image providers are listed in
  `CODH-provider.ja.txt`; no full book scan is included.
- **Academia Sinica 小學堂**: three individual glyph images under CC0 1.0.
  The selected fontcode identifies each record; fonts and full scans are not
  included. These assets remain candidates pending distinct asset review.

The corresponding license evidence URLs and exact pins are recorded in the
source registry. Changes to upstream bytes require a new source revision and
review, not an in-place overwrite of community claims.
