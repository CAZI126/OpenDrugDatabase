"""Explicitly separate regulatory source changes from derivative changes."""

from __future__ import annotations

from odd.models import ChangeCause, StoredDocumentVersion


def classify_change_cause(
    old: StoredDocumentVersion | None,
    new: StoredDocumentVersion | None,
) -> ChangeCause:
    components = change_components(old, new)
    if len(components) > 1:
        return ChangeCause.MULTIPLE_CAUSES
    return components[0]


def change_components(
    old: StoredDocumentVersion | None,
    new: StoredDocumentVersion | None,
) -> tuple[ChangeCause, ...]:
    if old is None and new is None:
        return (ChangeCause.NO_CHANGE,)
    if old is None or new is None:
        return (ChangeCause.SOURCE_CHANGED,)

    required = (
        old.provenance.raw_sha256,
        new.provenance.raw_sha256,
        old.provenance.parser_version,
        new.provenance.parser_version,
        old.provenance.schema_version,
        new.provenance.schema_version,
        old.provenance.mapping_version,
        new.provenance.mapping_version,
    )
    if not all(required):
        return (ChangeCause.UNDETERMINED,)

    causes: list[ChangeCause] = []
    if old.provenance.raw_sha256 != new.provenance.raw_sha256:
        causes.append(ChangeCause.SOURCE_CHANGED)
    if old.provenance.parser_version != new.provenance.parser_version:
        causes.append(ChangeCause.PARSER_CHANGED)
    if old.provenance.schema_version != new.provenance.schema_version:
        causes.append(ChangeCause.SCHEMA_CHANGED)
    if old.provenance.mapping_version != new.provenance.mapping_version:
        causes.append(ChangeCause.MAPPING_CHANGED)

    if causes:
        return tuple(causes)

    # Equal raw bytes cannot validly advertise two distinct embedded SPL versions.
    if old.provenance.source_version != new.provenance.source_version:
        return (ChangeCause.UNDETERMINED,)
    if old.normalized_sha256 != new.normalized_sha256:
        return (ChangeCause.UNDETERMINED,)
    if old.ingestion_metadata_sha256 != new.ingestion_metadata_sha256:
        return (ChangeCause.METADATA_ONLY_CHANGED,)
    return (ChangeCause.NO_CHANGE,)
