from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .yamlio import load

ID = re.compile(r"^[a-z0-9]+(?:[-.][a-z0-9]+)*$")
LOCALE = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{3})?(?:-(?:[A-Z]{2}|[0-9]{3}))?(?:-[A-Za-z0-9]{5,8})*$")
KINDS = {"visual-name", "semantic-function", "historical-phonetic", "modern-japanese-sound", "historical-origin", "reading-example", "mnemonic"}
STATUSES = {"candidate", "approved", "rejected", "stale", "withheld"}
REVIEW_STATES = {"pending", "approved", "rejected", "stale"}
SHA256 = re.compile(r"[0-9a-f]{64}")
REVIEWED_REVISIONS = Path("data/reviewed-claim-revisions.yaml")


class ValidationError(ValueError):
    pass


def need(condition: bool, path: Path, field: str, message: str) -> None:
    if not condition:
        raise ValidationError(f"{path}:{field}: {message}")


def exact_keys(obj: Any, keys: set[str], path: Path, field: str = "") -> None:
    need(isinstance(obj, dict), path, field or "$", "must be a mapping")
    actual = set(obj)
    need(actual <= keys, path, field or "$", f"unknown field(s): {', '.join(sorted(actual - keys))}")


def nonempty(value: Any, path: Path, field: str) -> None:
    need(isinstance(value, str) and bool(value.strip()), path, field, "must be a nonempty string")


def is_scalar(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 1 and not 0xD800 <= ord(value) <= 0xDFFF


def validate_locale(value: Any, path: Path, field: str) -> None:
    need(isinstance(value, str) and LOCALE.fullmatch(value) is not None, path, field, "must be a BCP 47 locale such as en, zh-Hant, or pt-BR")


def validate_url(value: Any, path: Path, field: str) -> None:
    need(isinstance(value, str), path, field, "must be an absolute HTTPS URL")
    parsed = urlparse(value)
    need(parsed.scheme == "https" and bool(parsed.netloc), path, field, "must be an absolute HTTPS URL")


def validate_registry(doc: Any, path: Path) -> tuple[dict[str, dict], dict[str, dict]]:
    exact_keys(doc, {"version", "sources", "references"}, path)
    need(doc.get("version") == 1, path, "version", "must equal 1")
    sources, refs = doc.get("sources"), doc.get("references")
    need(isinstance(sources, list), path, "sources", "must be a list")
    need(isinstance(refs, list), path, "references", "must be a list")
    source_by_id: dict[str, dict] = {}
    for i, source in enumerate(sources):
        field = f"sources[{i}]"
        exact_keys(source, {"id", "author", "project", "url", "license", "licenseVersion", "licenseEvidenceURL", "scope", "attribution", "modifications", "sourceLanguage", "upstream", "revision", "sha256", "acquisitionMethod", "retrievedAt"}, path, field)
        sid = source.get("id")
        need(isinstance(sid, str) and ID.fullmatch(sid), path, f"{field}.id", "malformed source id")
        need(sid not in source_by_id, path, f"{field}.id", "duplicate source id")
        for key in ("author", "project", "license", "licenseVersion", "scope", "attribution", "modifications", "revision", "acquisitionMethod", "retrievedAt"):
            nonempty(source.get(key), path, f"{field}.{key}")
        need(source.get("license") in {"CC-BY-SA", "CC-BY", "CC0", "Public-Domain", "MIT", "LicenseRef-ACC-Public-Domain-with-Fallback", "LicenseRef-GlyphWiki"}, path, f"{field}.license", "unknown license ID; define a scoped LicenseRef before importing")
        validate_url(source.get("url"), path, f"{field}.url")
        validate_url(source.get("licenseEvidenceURL"), path, f"{field}.licenseEvidenceURL")
        validate_locale(source.get("sourceLanguage"), path, f"{field}.sourceLanguage")
        try:
            datetime.fromisoformat(source["retrievedAt"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{path}:{field}.retrievedAt: must be an ISO-8601 timestamp") from exc
        need(isinstance(source.get("upstream"), list), path, f"{field}.upstream", "must be a list")
        digest = source.get("sha256")
        need(digest is None or re.fullmatch(r"[0-9a-f]{64}", str(digest)) is not None, path, f"{field}.sha256", "must be a lowercase SHA-256")
        source_by_id[sid] = source
    ref_by_id: dict[str, dict] = {}
    for i, ref in enumerate(refs):
        field = f"references[{i}]"
        exact_keys(ref, {"id", "source", "url", "externalId", "locator", "revision", "snapshotHash", "retrievedAt", "supports"}, path, field)
        rid = ref.get("id")
        need(isinstance(rid, str) and ID.fullmatch(rid), path, f"{field}.id", "malformed reference id")
        need(rid not in ref_by_id, path, f"{field}.id", "duplicate reference id")
        need(ref.get("source") in source_by_id, path, f"{field}.source", "unknown source id")
        for key in ("externalId", "locator", "revision", "retrievedAt"):
            nonempty(ref.get(key), path, f"{field}.{key}")
        validate_url(ref.get("url"), path, f"{field}.url")
        try:
            datetime.fromisoformat(ref["retrievedAt"].replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValidationError(f"{path}:{field}.retrievedAt: must be an ISO-8601 timestamp") from exc
        digest = ref.get("snapshotHash")
        need(isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest), path, f"{field}.snapshotHash", "must be a lowercase SHA-256")
        need(isinstance(ref.get("supports"), list) and ref["supports"], path, f"{field}.supports", "must describe what this reference supports")
        ref_by_id[rid] = ref
    return source_by_id, ref_by_id


def validate_claim(doc: Any, path: Path, refs: dict[str, dict]) -> dict:
    fields = {"id", "kind", "subject", "revision", "localizedRevision", "status", "claimText", "author", "license", "evidence", "review", "targetLanguage", "locale", "translationOf", "story"}
    exact_keys(doc, fields, path)
    cid = doc.get("id")
    need(isinstance(cid, str) and ID.fullmatch(cid), path, "id", "malformed claim id")
    need(doc.get("kind") in KINDS, path, "kind", "unknown claim kind")
    need(doc.get("status") in STATUSES, path, "status", "unknown status")
    subject = doc.get("subject")
    need(isinstance(subject, dict), path, "subject", "must use a typed subject mapping")
    subject_type = subject.get("type")
    if subject_type == "character":
        exact_keys(subject, {"type", "literal", "codepoint"}, path, "subject")
        literal = subject.get("literal")
        need(is_scalar(literal), path, "subject.literal", "must be one literal Unicode scalar")
        need(subject.get("codepoint") == f"U+{ord(literal):04X}", path, "subject.codepoint", "must match the literal")
    elif subject_type == "component":
        exact_keys(subject, {"type", "id"}, path, "subject")
        need(isinstance(subject.get("id"), str) and ID.fullmatch(subject["id"]), path, "subject.id", "malformed component ID")
    elif subject_type == "occurrence":
        exact_keys(subject, {"type", "structure", "occurrence"}, path, "subject")
        for key in ("structure", "occurrence"):
            nonempty(subject.get(key), path, f"subject.{key}")
    elif subject_type in {"reading", "asset", "sense"}:
        exact_keys(subject, {"type", "id"}, path, "subject")
        nonempty(subject.get("id"), path, "subject.id")
    else:
        raise ValidationError(f"{path}:subject.type: unsupported typed subject {subject_type!r}")
    nonempty(doc.get("revision"), path, "revision")
    nonempty(doc.get("localizedRevision"), path, "localizedRevision")
    nonempty(doc.get("claimText"), path, "claimText")
    validate_locale(doc.get("targetLanguage"), path, "targetLanguage")
    validate_locale(doc.get("locale"), path, "locale")
    author = doc.get("author")
    exact_keys(author, {"name", "type", "recordedAt"}, path, "author")
    nonempty(author.get("name"), path, "author.name")
    need(author.get("type") in {"human", "agent", "community"}, path, "author.type", "must be human, agent, or community")
    try:
        date.fromisoformat(str(author.get("recordedAt")))
    except ValueError as exc:
        raise ValidationError(f"{path}:author.recordedAt: must be YYYY-MM-DD") from exc
    need(doc.get("license") == "CC-BY-SA-4.0", path, "license", "new community content uses CC-BY-SA-4.0")
    evidence = doc.get("evidence")
    need(isinstance(evidence, list) and evidence, path, "evidence", "must bind this claim to at least one exact reference")
    for i, item in enumerate(evidence):
        field = f"evidence[{i}]"
        exact_keys(item, {"reference", "claimField", "supportType", "selector"}, path, field)
        ref = item.get("reference")
        need(isinstance(ref, str) and ref in refs, path, f"{field}.reference", "unknown reference id")
        nonempty(item.get("claimField"), path, f"{field}.claimField")
        nonempty(item.get("supportType"), path, f"{field}.supportType")
        nonempty(item.get("selector"), path, f"{field}.selector")
    review = doc.get("review")
    exact_keys(review, {"state", "reviewer", "reviewedAt", "claimRevision", "sourceRevision", "rationale"}, path, "review")
    need(review.get("state") in REVIEW_STATES, path, "review.state", "unknown review state")
    if doc["status"] == "approved":
        need(review["state"] == "approved", path, "review.state", "approved status requires an approved review")
    if review["state"] == "approved":
        nonempty(review.get("reviewer"), path, "review.reviewer")
        nonempty(review.get("reviewedAt"), path, "review.reviewedAt")
        nonempty(review.get("claimRevision"), path, "review.claimRevision")
        nonempty(review.get("sourceRevision"), path, "review.sourceRevision")
        nonempty(review.get("rationale"), path, "review.rationale")
        need(review.get("reviewer") != author.get("name"), path, "review.reviewer", "the reviewer must be a distinct person or review agent")
    if doc["status"] == "approved":
        need(review.get("claimRevision") == doc.get("revision"), path, "review.claimRevision", "approved review must bind the current claim revision")
        expected_source_revision = source_revision(evidence, refs)
        need(review.get("sourceRevision") == expected_source_revision, path, "review.sourceRevision", "approved review must bind the exact current evidence revisions")
    translation = doc.get("translationOf")
    if translation is not None:
        exact_keys(translation, {"claim", "locale", "textRevision"}, path, "translationOf")
        nonempty(translation.get("claim"), path, "translationOf.claim")
        validate_locale(translation.get("locale"), path, "translationOf.locale")
        nonempty(translation.get("textRevision"), path, "translationOf.textRevision")
    if doc.get("kind") == "mnemonic":
        exact_keys(doc.get("story"), {"locale", "originality", "targetReference", "targetSelector", "occurrences", "fiction", "textRevision"}, path, "story")
        story = doc["story"]
        validate_locale(story.get("locale"), path, "story.locale")
        need(story.get("originality") in {"original", "adapted"}, path, "story.originality", "must be original or adapted")
        nonempty(story.get("targetReference"), path, "story.targetReference")
        need(story.get("targetReference") in refs, path, "story.targetReference", "unknown target reference")
        nonempty(story.get("targetSelector"), path, "story.targetSelector")
        need(story.get("fiction") is True, path, "story.fiction", "the imagined scene must be explicitly marked as fiction")
        nonempty(story.get("textRevision"), path, "story.textRevision")
        need(story.get("textRevision") == doc.get("localizedRevision"), path, "story.textRevision", "must equal the localized text revision")
        occurrences = story.get("occurrences")
        need(isinstance(occurrences, list) and occurrences, path, "story.occurrences", "must bind to exact component occurrences")
        for i, occurrence in enumerate(occurrences):
            exact_keys(occurrence, {"structure", "occurrence", "labelClaim", "authoredForm", "crosswalk"}, path, f"story.occurrences[{i}]")
            for key in ("structure", "occurrence", "labelClaim"):
                nonempty(occurrence.get(key), path, f"story.occurrences[{i}].{key}")
            need(is_scalar(occurrence.get("authoredForm")), path, f"story.occurrences[{i}].authoredForm", "must be one literal Unicode scalar")
            need("crosswalk" in occurrence and (occurrence["crosswalk"] is None or isinstance(occurrence["crosswalk"], dict)),
                 path, f"story.occurrences[{i}].crosswalk", "must be null or an explicit crosswalk")
        need(doc.get("locale") == story.get("locale"), path, "locale", "must match the story locale")
    return doc


def source_revision(evidence: list[dict], refs: dict[str, dict]) -> str:
    snapshots = [refs[item["reference"]] for item in evidence]
    return "|".join(sorted(f"{ref['source']}:{ref['revision']}:{ref['snapshotHash']}" for ref in snapshots))


def _reviewable_claim(claim: dict, refs: dict[str, dict]) -> dict:
    return {
        "claim": {key: value for key, value in claim.items() if key not in {"status", "review"}},
        "references": [refs[item["reference"]] for item in claim["evidence"]],
    }


def claim_review_fingerprint(claim: dict, claims: dict[str, dict], refs: dict[str, dict], structures: dict[str, dict]) -> str:
    """Hash the exact inputs covered by editorial review using canonical JSON."""
    payload = _reviewable_claim(claim, refs)
    translation = claim.get("translationOf")
    if translation is not None:
        base = claims[translation["claim"]]
        payload["translatedText"] = {key: base[key] for key in ("locale", "localizedRevision", "claimText")}
    if claim["kind"] == "mnemonic":
        bindings = []
        for binding in claim["story"]["occurrences"]:
            structure = structures[binding["structure"]]
            occurrence = next(item for item in structure["occurrences"] if item["id"] == binding["occurrence"])
            bindings.append({
                "structure": {key: value for key, value in structure.items() if key != "occurrences"},
                "occurrence": occurrence,
                "label": _reviewable_claim(claims[binding["labelClaim"]], refs),
            })
        payload["bindings"] = bindings
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_reviewed_fingerprints(root: Path) -> dict[str, str]:
    path = root / REVIEWED_REVISIONS
    need(not path.is_symlink(), path, "$", "reviewed fingerprints must be stored in a regular repository file")
    if not path.exists():
        return {}
    doc = load(path)
    exact_keys(doc, {"version", "revisions"}, path)
    revisions = doc.get("revisions")
    need(doc.get("version") == 1 and isinstance(revisions, dict), path, "$", "requires version 1 and a revisions mapping")
    for cid, fingerprint in revisions.items():
        need(ID.fullmatch(cid) and isinstance(fingerprint, str) and SHA256.fullmatch(fingerprint), path, cid,
             "must map a claim ID to a lowercase SHA-256 fingerprint")
    return revisions


def load_project(root: Path) -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    registry_path = root / "sources" / "registry.yaml"
    source_by_id, ref_by_id = validate_registry(load(registry_path), registry_path)
    claims: list[dict] = []
    ids: set[str] = set()
    for path in sorted((root / "content").rglob("*.yaml")):
        claim = validate_claim(load(path), path, ref_by_id)
        need(claim["id"] not in ids, path, "id", f"duplicate claim id {claim['id']}")
        ids.add(claim["id"])
        claims.append(claim)
    return claims, source_by_id, ref_by_id


def _validate_claim_graph(
    root: Path,
    claims: list[dict],
    refs: dict[str, dict],
    imported: tuple,
    assets: list[dict],
) -> None:
    by_id = {claim["id"]: claim for claim in claims}
    characters = {row["literal"] for row in imported[0]}
    components = {row["id"] for row in imported[1]}
    structures = {row["id"]: row for row in imported[2]}
    occurrences = {
        (structure["id"], occurrence["id"]): occurrence
        for structure in structures.values()
        for occurrence in structure["occurrences"]
    }
    asset_ids = {row["id"] for row in assets}

    translations = {}
    for claim in claims:
        cid = claim["id"]
        subject = claim["subject"]
        kind = subject["type"]
        if kind == "character":
            exists = subject["literal"] in characters
        elif kind == "component":
            exists = subject["id"] in components
        elif kind == "occurrence":
            exists = (subject["structure"], subject["occurrence"]) in occurrences
        elif kind == "asset":
            exists = subject["id"] in asset_ids
        else:
            # Reading and sense candidates do not yet have a canonical subject index.
            exists = False
        need(exists, root, f"subject.{cid}", f"unknown {kind} subject")

        translation = claim.get("translationOf")
        if translation is not None:
            field = f"translationOf.{cid}"
            base_id = translation["claim"]
            base = by_id.get(base_id)
            need(base is not None, root, field, "unknown source claim")
            need(translation["locale"] == base["locale"], root, f"{field}.locale", "must match the source claim locale")
            need(claim["locale"] != base["locale"], root, f"{field}.locale", "translation must have a different locale from its source")
            for key in ("kind", "subject", "targetLanguage"):
                need(claim[key] == base[key], root, field, f"translation must preserve the source claim's {key}")
            translations[cid] = base_id

    walked: set[str] = set()
    for start in translations:
        trail: set[str] = set()
        cid = start
        while cid in translations and cid not in walked:
            need(cid not in trail, root, f"translationOf.{cid}", "translation cycle")
            trail.add(cid)
            cid = translations[cid]
        walked.update(trail)

    for claim in claims:
        cid = claim["id"]
        approved = claim["status"] == "approved"
        if approved and cid in translations:
            base = by_id[translations[cid]]
            need(base["status"] == "approved", root, f"translationOf.{cid}", "approved translation requires a currently approved source claim")
            need(claim["translationOf"]["textRevision"] == base["localizedRevision"], root, f"translationOf.{cid}",
                 "approved translation is stale against its source text revision")
        if claim["kind"] == "mnemonic":
            _validate_story(root, claim, by_id, structures, occurrences)

    reviewed = load_reviewed_fingerprints(root)
    for claim in claims:
        if claim["status"] != "approved":
            continue
        fingerprint = claim_review_fingerprint(claim, by_id, refs, structures)
        need(reviewed.get(claim["id"]) == fingerprint, root, f"review.{claim['id']}",
             "approved claim material or dependencies changed without a matching reviewed fingerprint")


def _validate_story(root: Path, claim: dict, claims: dict[str, dict], structures: dict, occurrences: dict) -> None:
    cid = claim["id"]
    subject = claim["subject"]
    story = claim["story"]
    need(subject["type"] == "character", root, f"subject.{cid}", "mnemonics must target a character")
    need(any(item["claimField"] == "story.targetReference" and item["reference"] == story["targetReference"]
             and item["selector"] == story["targetSelector"] for item in claim["evidence"]),
         root, f"story.{cid}.targetSelector", "must match the exact cited target evidence")
    seen: set[tuple[str, str]] = set()
    for i, binding in enumerate(story["occurrences"]):
        field = f"story.{cid}.occurrences[{i}]"
        struct = structures.get(binding["structure"])
        need(struct is not None, root, f"{field}.structure", "unknown structure ID")
        need(struct["literal"] == subject["literal"], root, f"{field}.structure", "structure must belong to the mnemonic's target character")
        key = binding["structure"], binding["occurrence"]
        occurrence = occurrences.get(key)
        need(occurrence is not None, root, f"{field}.occurrence", "unknown exact occurrence ID")
        need(key not in seen, root, f"{field}.occurrence", "duplicate occurrence binding")
        seen.add(key)
        crosswalk = binding["crosswalk"]
        actual_form, authored_form = occurrence["form"], binding["authoredForm"]
        need(authored_form == actual_form or crosswalk is not None, root, f"{field}.authoredForm",
             "a different authored glyph must have an explicit source crosswalk")
        if crosswalk is not None:
            crosswalk_field = f"{field}.crosswalk"
            exact_keys(crosswalk, {"fromCodepoint", "toCodepoint", "sourceAttribute", "reference"}, root, crosswalk_field)
            need(is_scalar(actual_form) and crosswalk.get("fromCodepoint") == f"U+{ord(actual_form):04X}", root,
                 f"{crosswalk_field}.fromCodepoint", "must identify the rendered group form exactly")
            need(crosswalk.get("toCodepoint") == f"U+{ord(authored_form):04X}", root,
                 f"{crosswalk_field}.toCodepoint", "must identify the authored selector glyph exactly")
            need(crosswalk.get("sourceAttribute") == "original" and crosswalk.get("reference") == struct["reference"], root,
                 crosswalk_field, "must cite the exact KanjiVG original attribute on the same structure")
            need(struct["source"].startswith("kanjivg-") and occurrence["attributes"].get("original") == authored_form, root, crosswalk_field,
                 "authored glyph must match the bound occurrence's recorded original attribute")
        label = claims.get(binding["labelClaim"])
        need(label is not None, root, f"{field}.labelClaim", "unknown label claim")
        need(label["kind"] == "visual-name" and label["subject"]["type"] == "component", root,
             f"{field}.labelClaim", "must bind to a component visual-name claim")
        need(label["subject"]["id"] == occurrence["component"], root, f"{field}.labelClaim",
             "label claim does not name the bound occurrence's component")
        if claim["status"] == "approved":
            need(label["status"] == "approved", root, f"{field}.labelClaim", "approved story requires a currently approved label")
            need(label["locale"] == claim["locale"] and label["targetLanguage"] == claim["targetLanguage"], root,
                 f"{field}.labelClaim", "approved story and label must have the same locale and target language")


def validate(root: Path, *, preloaded: tuple | None = None) -> tuple[int, int, int]:
    if preloaded is None:
        claims, sources, refs = load_project(root)
        imported = None
    else:
        claims, sources, refs, imported = preloaded
    # Import adapters and release builds share the same semantic contract.
    from .database import _assets, _imports, _intake, _imported_candidates
    if imported is None:
        imported = _imports(root, sources)
    _intake(root, refs)
    _imported_candidates(root, sources, refs)
    assets = _assets(root, sources, refs)
    _validate_claim_graph(root, claims, refs, imported, assets)
    return len(claims), len(sources), len(refs)
