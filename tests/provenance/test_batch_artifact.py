"""Canonical ODD-003 batch report identity tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from odd.provenance.canonical import canonical_batch_report_json_bytes
from odd.provenance.hashing import sha256_bytes
from tests.odd003_support import odd003_service


def test_operational_timestamps_do_not_change_batch_canonical_identity(
    tmp_path: Path,
) -> None:
    application, _transport = odd003_service(tmp_path)
    artifact = application.batch_run("us-top10-2023")
    later = datetime(2030, 1, 1, tzinfo=UTC)
    changed = replace(
        artifact.report,
        generated_at=later,
        batch_run=replace(
            artifact.report.batch_run,
            started_at=later - timedelta(hours=1),
            completed_at=later,
            canonical_report_sha256="f" * 64,
        ),
    )
    assert canonical_batch_report_json_bytes(changed) == artifact.canonical_json
    assert sha256_bytes(canonical_batch_report_json_bytes(changed)) == (
        artifact.canonical_sha256
    )


def test_canonical_batch_report_retains_version_identities(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    artifact = application.batch_run("us-top10-2023")
    payload = artifact.canonical_json.decode("utf-8")
    assert '"selection_rule_version":"dailymed-top10-validation-selection/1.0.0"' in payload
    assert '"parser_version":"spl-parser/1.0.0"' in payload
    assert '"schema_version":"odd-normalized/1.0.0"' in payload
    assert '"mapping_version":"spl-section-mapping/1.0.0"' in payload
