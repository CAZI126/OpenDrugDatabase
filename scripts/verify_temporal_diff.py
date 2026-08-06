"""Independent offline ODD-002 verification over two genuine DailyMed fixtures."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.odd002_support import (  # noqa: E402
    SET_ID,
    V29_SHA256,
    V30_SHA256,
    temporal_service,
)

EXPECTED_DIFF_ID = "13b99529-0bf8-54f8-a5e7-c7d0bcc3847f"
EXPECTED_DIFF_SHA256 = "89b1c4eb5ad64afbbc6a8709b904cdc2271b59405da9573854fb0865a8d1ca76"


def verify() -> dict[str, object]:
    with TemporaryDirectory(prefix="odd-002-") as temporary:
        application, old_id, new_id = temporal_service(Path(temporary))
        result = application.diff_documents(old_id, new_id)
        verification = application.verify_diff(result.diff.diff_id)
        evidence: dict[str, object] = {
            "canonical_diff_sha256": result.canonical_sha256,
            "change_cause": result.diff.change_cause.value,
            "diff_id": result.diff.diff_id,
            "new_raw_sha256": result.diff.new_raw_sha256,
            "new_source_version": result.diff.new_source_version,
            "old_raw_sha256": result.diff.old_raw_sha256,
            "old_source_version": result.diff.old_source_version,
            "ordering_status": result.diff.ordering_status.value,
            "set_id": result.diff.source_document_id,
            "summary": result.diff.summary,
            "verified": verification.ok,
        }
        expected = {
            "canonical_diff_sha256": EXPECTED_DIFF_SHA256,
            "change_cause": "SOURCE_CHANGED",
            "diff_id": EXPECTED_DIFF_ID,
            "new_raw_sha256": V30_SHA256,
            "new_source_version": "30",
            "old_raw_sha256": V29_SHA256,
            "old_source_version": "29",
            "ordering_status": "SOURCE_VERSION_ORDERED",
            "set_id": SET_ID,
            "verified": True,
        }
        mismatches = {
            key: {"expected": value, "actual": evidence[key]}
            for key, value in expected.items()
            if evidence[key] != value
        }
        if mismatches:
            raise RuntimeError(f"ODD-002 temporal fixture verification failed: {mismatches}")
        return evidence


def main() -> None:
    evidence = verify()
    print(
        "ODD-002 temporal fixture verification: OK "
        f"({evidence['old_source_version']} -> {evidence['new_source_version']}, "
        f"diff {evidence['canonical_diff_sha256']})"
    )


if __name__ == "__main__":
    main()
