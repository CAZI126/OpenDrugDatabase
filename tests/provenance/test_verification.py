"""Independent verification failure detection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from tests.odd_support import SET_ID, fetched_service


def test_section_hash_corruption_is_detected(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute(
            "UPDATE source_sections SET original_text = 'corrupted' WHERE sequence_index = 8"
        )
        connection.commit()
    result = application.verify(outcome.document_id)
    section_check = next(item for item in result.checks if item.name == "section_sha256")
    deterministic_check = next(
        item for item in result.checks if item.name == "deterministic_normalization"
    )
    assert result.ok is False
    assert section_check.ok is False
    # The stored canonical blob still reproduces; row-level corruption is independently detected.
    assert deterministic_check.ok is True


def test_required_provenance_corruption_is_detected(tmp_path: Path) -> None:
    application = fetched_service(tmp_path)
    outcome = application.ingest(SET_ID)
    with sqlite3.connect(application.repository.path) as connection:
        connection.execute("UPDATE source_documents SET provider = ''")
        connection.commit()
    result = application.verify(outcome.document_id)
    check = next(item for item in result.checks if item.name == "required_provenance")
    assert result.ok is False
    assert check.ok is False
    assert "provider" in check.message
