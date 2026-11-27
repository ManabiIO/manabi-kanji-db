# Japanese written-form data

Copyright English Wiktionary contributors. Adapted data is licensed under
[Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/).
This license covers the adapted data, separately from application code. Retain
attribution, the license link and modification notice when redistributing it;
distribute further adaptations under the same or a compatible ShareAlike license.
No endorsement is implied. The license supplies no warranties.

Source: [Module:ja/data/kyu, revision 92671213](https://en.wiktionary.org/w/index.php?title=Module:ja/data/kyu&oldid=92671213),
2026-09-13 09:10:14 UTC. [Contributor history](https://en.wiktionary.org/w/index.php?title=Module:ja/data/kyu&action=history).
[Wiktionary copyright declaration, revision 87545419](https://en.wiktionary.org/w/index.php?title=Wiktionary:Copyrights&oldid=87545419).

The adjacent `japanese-written-forms.lua` is the exact UTF-8 source, including its
category and ambiguity comments; SHA-256
`bc177eeb853fcfe53b42be9596b5903b521bbb1fa459952793f40ad462551161`.
The maintained Python adapter extracts 452 distinct exact codepoint pairs from
454 occurrences, decodes numeric entities, and merges duplicate pairs while
retaining every source category. It never evaluates Lua or normalizes Unicode.
In particular, compatibility ideographs retain their separate identity.

Parts 1/9 are jōyō categories and parts 4/10 are name-character categories.
The source's official-status labels have not been independently corroborated
against the official tables, so captions assert Japanese written-form relations
without adoption dates or an official-authority claim. Other categories remain
explicitly labelled variants and do not create chronological reform takeaways.
The comment-only 弁/辨/瓣/辯 ambiguity is a review gap, not an admitted relation.
These pairs do not establish ancient inscription forms or component lineage.

The generator must admit both exact endpoints through its existing strict
KanjiVG geometry parser before attaching a relationship. History-only geometry
does not expand the lexical lookup scope. Coverage distinguishes distinct pairs
from endpoint records, lexical absence, missing drawings and parser failures.
Reviewed captions are retained and take precedence over generic source captions.

To reproduce the immutable source in a fresh path (from ManabiDictionaries):

```sh
python3 Scripts/debug_kanji_written_forms.py --refresh-source /absolute/fresh-directory/japanese-written-forms.lua
python3 -m unittest discover -s Scripts -p test_debug_kanji_written_forms.py
```

The refresh command verifies page/revision identity and the pinned content hash
before exclusive creation. Review and deliberately replace the retained snapshot
only when changing the pin; ordinary generation never accesses the network.
The adapter returns source attribution for the generated in-app Sources notice.
KanjiVG geometry retains its separate existing CC BY-SA 3.0 attribution and
per-file checksums; this written-form snapshot contains no geometry.
