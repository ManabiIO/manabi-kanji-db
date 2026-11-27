# Imported source notices

Notices here apply only to the named material and do not license unrelated
fields or media. Each notice is retained beside a pinned source record in
`sources/registry.yaml`.

## Initial sources

- **KanjiVG** (`r20260714`): Ulrich Apel and contributors, CC BY-SA 3.0.
  Original notice: `KANJIVG-COPYING.txt`. Only Japanese stroke/group structure
  is imported; the complete KanjiVG drawings are not bundled in this project.
- **KANJIDIC2** (`2026-331`, file version 4): EDRDG and contributors, CC BY-SA
  4.0. Only literal and codepoint are retained as the overlay join.
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

The corresponding license evidence URLs and exact pins are recorded in the
source registry. Changes to upstream bytes require a new source revision and
review, not an in-place overwrite of community claims.
