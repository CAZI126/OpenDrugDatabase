"""Canonical UTF-8 JSON serialization for reproducible normalized output."""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, cast

from odd.models import BatchReport, DocumentDiff, NormalizedDocument, SourceIdentity


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize supported values with sorted keys and no insignificant whitespace."""

    return json.dumps(
        _primitive(value),
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_normalized_json_bytes(value: NormalizedDocument) -> bytes:
    """Serialize normalized data without retrieval-time transport metadata.

    ``retrieved_at`` and ``source_url`` remain available through the source record,
    but they cannot change parser output for identical source bytes and versioned
    parser inputs.
    """

    payload = _primitive(value)
    document = payload["document"]
    identity = document["source_identity"]
    identity.pop("retrieved_at", None)
    identity.pop("source_url", None)
    return canonical_json_bytes(payload)


def canonical_diff_json_bytes(value: DocumentDiff) -> bytes:
    """Serialize a diff artifact independently of its generation timestamp.

    ``generated_at`` and retrieval time are retained as separately stored
    generation/source metadata. Absolute storage roots are represented by a
    stable logical raw path. These operational values therefore cannot make the
    same compared source identities produce different artifact bytes.
    """

    payload = _primitive(value)
    payload["generated_at"] = None
    for name in ("old_provenance", "new_provenance"):
        provenance = payload.get(name)
        if not isinstance(provenance, dict):
            continue
        provenance["retrieved_at"] = None
        provenance["raw_path"] = "/".join(
            (
                "dailymed",
                str(provenance["source_document_id"]),
                str(provenance["source_version"]),
                "label.xml",
            )
        )
    return canonical_json_bytes(payload)


def canonical_batch_report_json_bytes(value: BatchReport) -> bytes:
    """Serialize a derivative batch report without operational timestamps.

    The utilization-list retrieval timestamp remains part of the versioned external
    input. Batch start, completion, and report-generation times describe execution,
    so they cannot change the identity of a report regenerated from the same stored
    item results.
    """

    payload = _primitive(value)
    payload["generated_at"] = None
    batch_run = payload["batch_run"]
    batch_run["started_at"] = None
    batch_run["completed_at"] = None
    batch_run["canonical_report_sha256"] = None
    if batch_run.get("observation_mode") == "LIVE":
        batch_run["batch_run_id"] = None
        for item in payload.get("items", []):
            if isinstance(item, dict):
                item["batch_run_id"] = None
                if item.get("ingestion_status") == "ALREADY_FETCHED":
                    item["ingestion_status"] = "FETCHED"
                elif item.get("ingestion_status") == "ALREADY_INGESTED":
                    item["ingestion_status"] = "INGESTED"
    return canonical_json_bytes(payload)


def source_identity_payload(identity: SourceIdentity) -> dict[str, Any]:
    """Return complete provenance, including operational retrieval metadata."""

    return cast(dict[str, Any], _primitive(identity))


def _primitive(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _primitive(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _primitive(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_primitive(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")
