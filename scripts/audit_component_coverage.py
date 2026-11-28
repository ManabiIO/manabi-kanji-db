"""Compare dictionary lookup availability with reviewed English labels on Japanese glyphs."""

import argparse
import collections
import gzip
import hashlib
import itertools
import json
import os
import sqlite3
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path


def reviewed_label_disposition(database, decisions):
    if decisions.get("version") != 1:
        raise ValueError("unsupported component-label review manifest")
    withheld = decisions.get("withheld")
    if not isinstance(withheld, list):
        raise ValueError("component-label review manifest requires a withheld list")
    for item in withheld:
        if item.get("decision") != "withhold":
            raise ValueError("coverage report may include only withheld label decisions")
        reference = database.execute(
            "SELECT source_id, revision, snapshot_hash FROM reference WHERE id=?",
            (item["reference"],),
        ).fetchone()
        if reference != (item["source"], item["sourceRevision"], item["sourceSHA256"]):
            raise ValueError(f"{item['form']}: withheld decision source pin differs from the database")
        groups = database.execute("""
            SELECT s.literal, o.occurrence_id, o.visible_form
            FROM occurrence o JOIN structure s ON s.id=o.structure_id
            WHERE o.structure_id=? AND o.occurrence_id IN (?, ?)
            ORDER BY o.occurrence_id
        """, (item["structure"], *item["sourceGroups"])).fetchall()
        expected = [(item["character"], group, item["form"]) for group in sorted(item["sourceGroups"])]
        if groups != expected:
            raise ValueError(f"{item['form']}: withheld decision no longer resolves to the recorded subject-local groups")
    return {
        "reviewer": decisions["reviewer"],
        "reviewedAt": decisions["reviewedAt"],
        "approvedLabels": decisions["approvedLabels"],
        "withheld": withheld,
    }


def inventory(database, baseline, decisions):
    data = baseline.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    pin = database.execute(
        "SELECT sha256 FROM source WHERE id IN (SELECT baseline_source_id FROM character)"
    ).fetchone()
    if pin is None or digest != pin[0]:
        raise ValueError("KANJIDIC2 archive differs from the database baseline")
    dictionary = ET.fromstring(gzip.decompress(data))
    joyo = set()
    glossed = set()
    for entry in dictionary.findall("character"):
        literal = entry.findtext("literal")
        if entry.findtext("misc/grade") in {"1", "2", "3", "4", "5", "6", "8"}:
            joyo.add(literal)
        if any(m.text and m.get("m_lang", "en") == "en"
               for m in entry.findall("reading_meaning/rmgroup/meaning")):
            glossed.add(literal)
    radicals = {r[0] for r in database.execute("SELECT literal FROM radical_name WHERE english_meaning != ''")}
    # Unify Kangxi radical code points only for the lookup test. Retain every displayed key.
    radicals.update(unicodedata.normalize("NFKC", c) for c in tuple(radicals) if len(c) == 1 and
                    0x2F00 <= ord(c) <= 0x2FD5)
    labels = {r[0] for r in database.execute("""
        SELECT c.subject_id FROM claim c JOIN localized_text t ON t.claim_id=c.id
        WHERE c.kind='visual-name' AND c.subject_type='component' AND c.review_state='approved'
          AND c.review_claim_revision=c.revision AND t.locale='en' AND t.stale=0
    """)}
    named = collections.defaultdict(set)
    originals = collections.defaultdict(set)
    components = collections.defaultdict(set)
    unnamed = []
    rows = database.execute("""
        SELECT s.literal, o.occurrence_id, o.component_id, o.parent_id, o.visible_form,
               json_extract(o.source_attributes_json,'$.original'), json_array_length(o.stroke_ids_json)
        FROM occurrence o JOIN structure s ON s.id=o.structure_id ORDER BY s.literal, o.occurrence_id
    """)
    for literal, occurrences in itertools.groupby(rows, key=lambda row: row[0]):
        if literal not in joyo:
            continue
        occurrences = list(occurrences)
        parent_ids = {row[3] for row in occurrences}
        for _, group, component, parent, form, original, strokes in occurrences:
            if parent is None:
                continue
            if form:
                named[form].add(literal)
                components[form].add(component)
                if original:
                    originals[form].add(original)
            elif group not in parent_ids:
                unnamed.append({"character": literal, "group": group, "strokes": strokes})
    uncovered = sorted(form for form in named if not ({form} | originals[form]) & (glossed | radicals))
    reviewed = sorted(form for form in named if components[form] & labels)
    return {
        "scope": "KANJIDIC2 grades 1–6 and 8; KanjiVG descendant groups; exact displayed keys",
        "baselineArchiveSHA256": digest,
        "componentLabelReview": reviewed_label_disposition(database, decisions),
        "joyo": len(joyo),
        "namedForms": len(named),
        "formsWithReviewedEnglishVisualLabel": len(reviewed),
        "lookupGaps": uncovered,
        "formsWithoutReviewedEnglishVisualLabel": sorted(set(named) - set(reviewed)),
        "unnamedLeaves": len(unnamed),
        "unnamedMultistrokeLeaves": sum(row["strokes"] > 1 for row in unnamed),
        "unnamedLeafSelectors": unnamed,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("kanjidic2_gz", type=Path)
    parser.add_argument("--review-decisions", type=Path, default=Path("data/coverage/component-label-review.json"))
    parser.add_argument("--output", type=Path, default=Path("data/coverage/component-inventory.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve(strict=True).parents[1]
    review_path = args.review_decisions if args.review_decisions.is_absolute() else root / args.review_decisions
    for path in (args.database, args.kanjidic2_gz, review_path):
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f"database and pinned baseline must be regular non-symlink files: {path}")
    database = args.database.resolve(strict=True)
    baseline = args.kanjidic2_gz.resolve(strict=True)
    output = args.output if args.output.is_absolute() else root / args.output
    if output.is_symlink() or output.parent.resolve(strict=True) != (root / "data/coverage").resolve(strict=True):
        raise SystemExit("inventory output must be a non-symlink file directly under data/coverage")
    decisions = json.loads(review_path.resolve(strict=True).read_text())
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        result = inventory(db, baseline, decisions)
    encoded = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=".component-inventory-", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, output)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    print(f"wrote {output.relative_to(root)} sha256={hashlib.sha256(encoded).hexdigest()}")
