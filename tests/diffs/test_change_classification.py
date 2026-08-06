from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from odd.diffs.classification import change_components, classify_change_cause
from odd.models import ChangeCause, DiffDocumentProvenance, StoredDocumentVersion


def _document() -> StoredDocumentVersion:
    provenance = DiffDocumentProvenance(
        authority="FDA",
        provider="DailyMed",
        jurisdiction="United States",
        source_document_id="same-set-id",
        source_version="29",
        source_instance_id="source-instance",
        effective_date=date(2023, 1, 1),
        publication_date=date(2023, 1, 2),
        publication_date_source="DAILYMED_HISTORY",
        retrieved_at=datetime(2023, 1, 3, tzinfo=UTC),
        raw_sha256="a" * 64,
        raw_path="raw.xml",
        parser_version="parser/1",
        schema_version="schema/1",
        mapping_version="mapping/1",
    )
    return StoredDocumentVersion(
        document_id="document-1",
        provenance=provenance,
        document_type="LABEL",
        language="en-US",
        title="Title",
        generic_name="apixaban",
        brand_names=("ELIQUIS",),
        dosage_forms=("TABLET",),
        routes=("ORAL",),
        active_ingredients=("APIXABAN",),
        normalized_sha256="1" * 64,
        ingestion_metadata_sha256="2" * 64,
        sections=(),
    )


@pytest.mark.parametrize(
    ("field", "expected"),
    (
        ("raw", ChangeCause.SOURCE_CHANGED),
        ("parser", ChangeCause.PARSER_CHANGED),
        ("schema", ChangeCause.SCHEMA_CHANGED),
        ("mapping", ChangeCause.MAPPING_CHANGED),
        ("metadata", ChangeCause.METADATA_ONLY_CHANGED),
    ),
)
def test_each_change_dimension_is_classified_explicitly(
    field: str, expected: ChangeCause
) -> None:
    old = _document()
    provenance = old.provenance
    new = replace(old, document_id="document-2")
    if field == "raw":
        provenance = replace(provenance, raw_sha256="b" * 64, source_version="30")
        new = replace(new, provenance=provenance, normalized_sha256="3" * 64)
    elif field == "parser":
        provenance = replace(provenance, parser_version="parser/2")
        new = replace(new, provenance=provenance, normalized_sha256="3" * 64)
    elif field == "schema":
        provenance = replace(provenance, schema_version="schema/2")
        new = replace(new, provenance=provenance, normalized_sha256="3" * 64)
    elif field == "mapping":
        provenance = replace(provenance, mapping_version="mapping/2")
        new = replace(new, provenance=provenance, normalized_sha256="3" * 64)
    else:
        provenance = replace(
            provenance, retrieved_at=provenance.retrieved_at + timedelta(days=1)
        )
        new = replace(
            new,
            document_id=old.document_id,
            provenance=provenance,
            ingestion_metadata_sha256="4" * 64,
        )

    assert classify_change_cause(old, new) == expected
    assert change_components(old, new) == (expected,)


def test_multiple_derivative_and_source_causes_are_not_collapsed() -> None:
    old = _document()
    new = replace(
        old,
        document_id="document-2",
        provenance=replace(
            old.provenance,
            source_version="30",
            raw_sha256="b" * 64,
            parser_version="parser/2",
            mapping_version="mapping/2",
        ),
        normalized_sha256="3" * 64,
    )

    assert classify_change_cause(old, new) == ChangeCause.MULTIPLE_CAUSES
    assert change_components(old, new) == (
        ChangeCause.SOURCE_CHANGED,
        ChangeCause.PARSER_CHANGED,
        ChangeCause.MAPPING_CHANGED,
    )


def test_equal_version_dimensions_and_bytes_are_no_change() -> None:
    document = _document()
    assert classify_change_cause(document, document) == ChangeCause.NO_CHANGE


def test_unexplained_normalized_difference_is_undetermined() -> None:
    old = _document()
    new = replace(old, document_id="document-2", normalized_sha256="9" * 64)
    assert classify_change_cause(old, new) == ChangeCause.UNDETERMINED


def test_document_addition_and_removal_are_source_changes() -> None:
    document = _document()
    assert classify_change_cause(None, document) == ChangeCause.SOURCE_CHANGED
    assert classify_change_cause(document, None) == ChangeCause.SOURCE_CHANGED
