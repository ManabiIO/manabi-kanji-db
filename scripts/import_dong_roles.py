"""Project the pinned Dong component roles for the selected Manabi teaching characters."""

import argparse
import hashlib
import json
from pathlib import Path

PIN = "046249581c3414baa12b6eff4a8d3c31ef1be7f70634fe919dfa1c01e99ab3eb"


def project(snapshot, subjects):
    if hashlib.sha256(snapshot).hexdigest() != PIN:
        raise ValueError("Dong dictionary snapshot SHA-256 differs from the selected release")
    for line, raw in enumerate(snapshot.splitlines(), 1):
        row = json.loads(raw)
        literal = row.get("char")
        if literal not in subjects or b"outlier" in raw.lower():
            continue
        lineage = row.get("sources", [])
        if "dong-chinese" not in lineage:
            continue
        for index, component in enumerate(row.get("components", [])):
            form = component.get("character")
            roles = component.get("type", [])
            if not isinstance(form, str) or not isinstance(roles, list):
                continue
            for role in roles:
                if role not in {"sound", "meaning"}:
                    continue
                yield {
                    "id": f"dong-{line}-{index}-{role}", "kind": "dong-component-role",
                    "subject": {"type": "character", "literal": literal},
                    "payload": {"component": form, "role": role, "upstreamLineage": lineage},
                    "source": "dong-character-wiki", "sourceRevision": "2025-12-27",
                    "reference": "dong-dictionary-2025-12-27",
                    "selector": f"line={line}; char={literal}; components[{index}].type={role}",
                    "sourceStatus": "source-candidate", "japaneseApplicability": "unreviewed",
                    "reviewState": "pending-independent-review", "publishable": False,
                }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dictionary", type=Path)
    args = parser.parse_args()
    donor_file = Path(__file__).resolve().parents[1] / "data/imports/donor-v26.jsonl"
    donor = map(json.loads, donor_file.read_text().splitlines())
    subjects = {r["payload"]["key"].split("/")[0] for r in donor
                if r["kind"] == "donor-v26-occurrenceReviews"} | {"清", "晴", "精", "請", "情"}
    for candidate in project(args.dictionary.read_bytes(), subjects):
        print(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")))
