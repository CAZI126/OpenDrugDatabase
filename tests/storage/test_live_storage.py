"""SQLite schema-v4 persistence and live evidence integrity tests."""

from __future__ import annotations

import sqlite3

from odd.models import DiscoveryCompleteness
from tests.odd004_support import live_service


def test_live_observation_persists_pages_decisions_and_item_state(tmp_path) -> None:
    application, _transport = live_service(tmp_path)
    run, items = application.batch_plan("us-top10-2023", new_observation=True)

    assert application.repository.schema_versions() == ("1", "2", "3", "4")
    assert application.repository.table_count("candidate_discovery_details") == 10
    assert application.repository.table_count("candidate_discovery_pages") == 10
    assert application.repository.table_count("live_batch_runs") == 1
    assert application.repository.table_count("live_batch_items") == 10
    reconstructed = application.repository.get_candidate_lookup(
        items[0].discovery_run_id or ""
    )
    assert reconstructed is not None
    assert reconstructed.snapshot_id == items[0].snapshot_id
    assert reconstructed.completeness is DiscoveryCompleteness.COMPLETE
    assert reconstructed.pages[0].raw_sha256
    assert application.repository.get_live_batch_run(run.batch_run_id) == run


def test_database_page_tampering_is_detected_without_changing_filesystem(tmp_path) -> None:
    application, _transport = live_service(tmp_path)
    _run, items = application.batch_plan("us-top10-2023", new_observation=True)
    snapshot_id = items[0].snapshot_id
    assert snapshot_id is not None
    assert all(application.repository.discovery_snapshot_integrity(snapshot_id).values())

    with sqlite3.connect(application.repository.path) as connection:
        connection.execute(
            """
            UPDATE candidate_discovery_pages SET raw_response = ?
            WHERE discovery_run_id = ? AND page_number = 1
            """,
            (b'{"tampered":true}', items[0].discovery_run_id),
        )
        connection.commit()

    verification = application.repository.discovery_snapshot_integrity(snapshot_id)
    assert verification["page_hashes"] is False
