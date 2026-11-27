from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .validation import validate_registry
from .yamlio import load


def audit(root: Path, output: Path, *, refresh: bool, limit: int = 100, offset: int = 0) -> int:
    if limit < 1 or offset < 0:
        raise ValueError("citation audit limit must be positive and offset must be nonnegative")
    registry_path = root / "sources" / "registry.yaml"
    _, refs = validate_registry(load(registry_path), registry_path)
    queue = []
    ordered = sorted(refs.items())
    stop = offset + limit if refresh else len(ordered)
    selected = set(range(offset, min(stop, len(ordered))))
    for index, (rid, ref) in enumerate(ordered):
        item = {"reference": rid, "url": ref["url"], "revision": ref["revision"], "snapshotHash": ref["snapshotHash"],
                "result": "pinned-not-retrieved", "reviewedByHuman": False}
        if refresh:
            if index not in selected:
                item.update(result="not-in-requested-batch", reviewedByHuman=False)
                queue.append(item)
                continue
            req = urllib.request.Request(ref["url"], headers={"User-Agent": "manabi-kanji-db-citation-audit/1.0"}, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=12) as response:
                    content = response.read(16 * 1024 * 1024 + 1)
                    headers = getattr(response, "headers", None)
                    content_type = headers.get_content_type() if headers and hasattr(headers, "get_content_type") else None
                    item.update(httpStatus=response.status, finalURL=response.geturl(), contentType=content_type)
                    if len(content) > 16 * 1024 * 1024:
                        item.update(result="retrieved-too-large-to-hash", reviewedByHuman=False,
                                    reviewReason="retrieved response exceeds the audit size limit")
                        queue.append(item)
                        continue
                    digest = hashlib.sha256(content).hexdigest()
                    url = ref["url"].lower()
                    url_path = urlsplit(url).path
                    raw_media = content_type is not None and (
                        content_type.startswith(("image/", "audio/", "video/")) or
                        content_type in {"application/pdf", "application/octet-stream"}
                    )
                    raw_snapshot = ("raw.githubusercontent.com/" in url or "action=raw" in url or
                                    "upload.wikimedia.org/" in url or
                                    url_path.endswith((".xml.gz", ".svg", ".csv", ".tsv", ".jsonl")) or
                                    raw_media)
                    if raw_snapshot:
                        item.update(result="retrieved-raw-snapshot", retrievedHash=digest,
                                    hashMatches=(digest == ref["snapshotHash"]), reviewedByHuman=False)
                        if digest != ref["snapshotHash"]:
                            item["reviewReason"] = "retrieved raw bytes differ from the pinned snapshot; human review required"
                    else:
                        item.update(result="retrieved-revision-page", responseSHA256=digest,
                                    hashCompared=False, reviewedByHuman=False,
                                    reviewReason="page revision retrieved; source snapshot hash is not the rendered HTTP body hash")
            except (urllib.error.URLError, TimeoutError, ValueError) as exc:
                item.update(result="retrieval-failed", error=f"{type(exc).__name__}: {exc}", reviewedByHuman=False)
            item["checkedAt"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        queue.append(item)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"schemaVersion": 1, "refreshPerformed": refresh, "requestedOffset": offset if refresh else None,
                                  "requestedLimit": limit if refresh else None, "humanApprovalGranted": False,
                                  "items": queue}, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return len(queue)
