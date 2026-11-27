# Contributing

Choose one character, visible form, or source correction. Give reviewers a concrete question, such as whether a particular 青 group supplies a useful clue to a selected Japanese on reading. A community patch can include an unresolved item while its evidence is being investigated.

## Start from the glyph

Join a character to the external KANJIDIC2 baseline by literal and codepoint. Look up the pinned Japanese decomposition and identify the exact group or stroke set. For 林, specify which 木 you mean. Keep source group identities when strokes form a split component. An encoded lookalike is insufficient to identify an unencoded fragment.

Choose the kind of contribution before writing the explanation. Visual labels describe what someone can see. Semantic and historical phonetic claims describe an evidenced role in formation. A present-day sound clue connects an occurrence to a particular Japanese reading. A fictional scene can help recall a meaning without implying any historical connection.

## Supply evidence for each fact

Reuse the source record when it already exists. Add an exact reference identifying an upstream record, its public URL and the passage, row, or group that supports the claim. Include the immutable revision or retrieval timestamp and content hash. Bind each claim to its references. Check whether two sources derive from the same dataset before treating them as corroboration.

For an example, identify the intended JMdict entry and spelling/reading combination. Check that the alignment supports the reading assigned to this kanji. A grouped ruby annotation may cover several characters. A missing common example leaves an attested reading eligible for further investigation.

## Check rights before importing

Record the grant for the field, passage or asset you propose to redistribute. Preserve its original attribution and record changes. For images, supply the description page, media URL, license evidence, creator, revision, and image type. A modern tracing and a photographed inscription require different descriptions. A source can supply a factual citation even when its wording or images cannot be redistributed.

Keep imported assertions and editorial changes in their respective collections. Re-running a source adapter must preserve community edits. Put unresolved rights, contradictory evidence and incomplete selectors in intake with the specific reason and the next decision needed.

## Write labels, stories and translations

For a new visual nickname, cite the Japanese glyph and exact occurrence that makes the name recognizable. For a mnemonic, choose a sourced meaning or reading, bind the labeled occurrences visible in the chosen glyph, and write a short scene that calls the target to mind. Credit its author and state whether it is original or adapted. Adaptations require a compatible grant and precise attribution. An original story has no external source for its fictional events.

Specify the target language and reader locale separately. An English explanation can describe Japanese using Japanese-language evidence. When translating, identify the exact revision of the localized text you translated. A change to that text requires a stale designation until the translation is checked again. Independently authored localized wording has its own revision history.

## Review and qualify

A different reviewer checks the cited evidence, Japanese applicability, rights, and usefulness of the actual wording. Record the reviewed revisions, date, reviewer identity and type, decision, and reason. Identify automated or agent review explicitly. Reassess approvals when the facts, evidence, labels, or text they depend on change.

Run the shared validator and tests from the repository root.

```sh
python -m kanjidb validate
python -m unittest discover -s tests
python -m kanjidb verify-reproducible
```

Maintainers dispatch **Validate a pull request** from main with the PR number and its full current head SHA. Check that the successful `kanji-db/manual-validation` status belongs to the revision being merged. Repeat after any push to that PR. A schema migration may need staged backward compatibility so the trusted validator can check the submitted content.

**Qualify and optionally publish main** runs on manual dispatch. Publishing defaults to off. Select it to release a qualified main snapshot and its checksums.

## Contribution terms

By submitting original data, explanations, translations, mnemonic stories or documentation, you agree to license your contribution under CC BY-SA 4.0. Newly written software, schemas, and tests use MIT. Include the original rights and attribution for third-party material and identify any modifications.
