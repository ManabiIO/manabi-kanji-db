# ManabiIO Kanji DB

ManabiIO Kanji DB is a community maintained, open data overlay for kanji. It
keeps Japanese glyph structure, component labels, occurrence roles, readings,
historical evidence, and mnemonic stories traceable to their sources. The
canonical authoring format is small YAML files; the release format is a
deterministic, indexed SQLite snapshot.

The overlay identifies KANJIDIC2 entries by the exact literal Unicode scalar
and its `U+` codepoint. It does not duplicate general readings, glosses,
frequency, grades, strokes, or dictionary IDs. Claims identify the specific
source, revision, selector and rights scope that supports them. Candidate or
unresolved material remains out of the current approved learner view.

## Licenses

| Material | License |
| --- | --- |
| Community data, original stories, localizations and docs | [CC BY-SA 4.0](LICENSE-DATA) |
| New code, schemas, importers, validators, build tools and tests | [MIT](LICENSE-CODE) |
| Imported fields and assets | Their recorded source grant and notice; no blanket relicensing |

KanjiVG source notices retain CC BY-SA 3.0. Public-domain and CC0 source work
is identified at its own field or asset boundary. The data license does not
change third-party rights or make source software grants applicable to data.

## Commands

Install the pinned Python dependency with `python3 -m pip install -r requirements.txt`,
then run these commands from the repository root:

```sh
python -m unittest discover -s tests
python -m kanjidb validate
python -m kanjidb build --output dist/kanji.sqlite
python -m kanjidb verify-reproducible
python -m kanjidb package --output dist/manabi-kanji-db-release.zip
python -m kanjidb audit-citations
python -m kanjidb audit-citations --refresh
```

Validation and build share the same strict YAML reader and semantic checks.
The citation refresh command creates a finite review queue; retrieval success
does not approve a source or claim. It never edits authored content.

## Data layout

- `sources/registry.yaml` records source grants and exact public references.
- `data/` stores source pinned character identities and visible structures.
- `data/joyo-appendix.yaml` stores official whole word readings and exact JMdict entry links.
- `data/coverage/` records import totals, source dispositions and component
  lookup gaps; `data/imports/` contains unpublishable source candidates.
- `content/` stores authored, revisioned claims and localized text.
- `intake/` holds typed unresolved provenance and rights work, excluded from
  approved learner projections.
- `source-notices/` preserves the upstream notices required for redistributed
  source material.
- `schemas/` documents the YAML contracts.

Sources and user authored claims are separate: a source importer updates only
its own `data/imports` area and never replaces content under `content/`.
Translations point to one exact localized revision. Independently authored
text in another locale does not depend on English wording. Fictional mnemonic
scenes are labeled as fiction and bind to exact component occurrences and
source backed labels.

## Scope and attribution

The [reuse catalogue](sources/reuse-scopes.json) records field and asset restrictions across
45 researched sources. The [registry](sources/registry.yaml) records the pins used by the database.
The [coverage manifests](data/coverage) identify imported donor rows, public passage bindings,
component naming gaps, example-reading decisions, 181 independently approved donor claims,
11 held revisions, and source candidates awaiting review.

### Using a snapshot

Verify the archive checksums, then open the SQLite file read-only and check
`PRAGMA user_version` against the supported `databaseSchemaVersion` in the
release manifest. Join Reader's existing KANJIDIC2 entry to `character` by exact
literal and codepoint.

Use `current_approved_claim` for localized learner text. In database schema version 4,
join an occurrence claim's `(subject_structure_id, subject_id)` to
`occurrence` on `(structure_id, occurrence_id)`. For a mnemonic, follow each
`story_occurrence` to its versioned structure, occurrence ID, and reviewed label.
For a citation, follow `claim_evidence.reference_id` to `reference` and then to `source`.

To find approved component-role claims by the exact visible form, use the indexed
`approved_component_role` view. This reports reviewed semantic functions,
historical phonetic roles, and modern Japanese sound clues attached to the exact
structure and occurrence:

```sql
SELECT character_literal, structure_id, occurrence_id, role_kind, claim_id, text
FROM approved_component_role
WHERE visible_form = '青'
ORDER BY role_kind, character_literal;
```

This result is distinct from visible membership: `visible_component_occurrence`
lists every glyph occurrence, whether or not a reviewed claim assigns a function.
Join `claim_evidence` and `reference` by `claim_id` and `reference_id` to inspect
the exact citation selectors behind each role.

Database schema version 4 adds the 2010 Jōyō Kanji appendix word-reading overlay.
`official_joyo_appendix_reading` retains the exact spelling, reading, source
row ordinal, and whether the pair is primary, an alternate explicitly given in a note,
or a printed example. Its `jmdict_entry_id` links to the matching JMdict entry
sequence; the overlay does not copy dictionary readings or meanings. Keep the
reading-to-entry association when joining JMdict so its `re_restr` and
`re_nokanji` fields remain authoritative for the exact spelling/reading pair.
Apply `stagk` and `stagr` if a dictionary view also displays sense text. The
appendix is word-level attestation and does not provide character reading
alignments.

Initial structural coverage follows the pinned KanjiVG release and the
KANJIDIC2 identity baseline. Each release includes the generated database,
input manifest, checksums, schema, attribution and source notices. Review
counts distinguish imported candidates, Japanese applicability, editorial
approval, redistribution permission, and current publication eligibility.
