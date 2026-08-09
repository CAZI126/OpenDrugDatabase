"""Independently verify the versioned ODD-004 live-observation contract offline."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from odd import __version__
from odd.connectors.dailymed.client import (
    HUMAN_PRESCRIPTION_DOCUMENT_CODE,
    LIVE_PAGE_SIZE,
)
from odd.constants import (
    BATCH_REPORT_VERSION,
    BATCH_SELECTION_RULE_VERSION,
    CONNECTOR_VERSION,
    LIVE_SNAPSHOT_VERSION,
    RAW_MANIFEST_VERSION,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import live_candidate_snapshot_id
from odd.storage.sqlite import DATABASE_SCHEMA_VERSION, SQLiteRepository

EXPECTED_TABLES = (
    "candidate_discovery_details",
    "candidate_discovery_pages",
    "live_batch_artifacts",
    "live_batch_items",
    "live_batch_runs",
)
EXPECTED_CONTRACT_SHA256 = "7620d3580fa2c46d4e78d2d1f37c30947ae5a1af12342be15fbb814bb1eb464d"


def main() -> None:
    if __version__ != "0.5.0":
        raise SystemExit(f"ODD package version is {__version__}, expected 0.5.0")
    repository_root = Path(__file__).resolve().parents[1]
    temporary_root = repository_root / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="odd004-contract-", dir=temporary_root) as temporary:
        repository = SQLiteRepository(Path(temporary) / "contract.sqlite3")
        repository.initialize_schema()
        if repository.schema_versions() != ("1", "2", "3", "4", "5"):
            raise SystemExit(
                f"unexpected migrations: {repository.schema_versions()}"
            )
        for table in EXPECTED_TABLES:
            repository.table_count(table)

    canonical_request = (
        ("doctype", HUMAN_PRESCRIPTION_DOCUMENT_CODE),
        ("drug_name", "atorvastatin"),
        ("endpoint", "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json"),
        ("name_type", "generic"),
        ("pagesize", str(LIVE_PAGE_SIZE)),
    )
    first = live_candidate_snapshot_id(
        canonical_request,
        ((1, "a" * 64), (2, "b" * 64)),
        connector_version=CONNECTOR_VERSION,
    )
    repeated = live_candidate_snapshot_id(
        canonical_request,
        ((1, "a" * 64), (2, "b" * 64)),
        connector_version=CONNECTOR_VERSION,
    )
    changed = live_candidate_snapshot_id(
        canonical_request,
        ((1, "a" * 64), (2, "c" * 64)),
        connector_version=CONNECTOR_VERSION,
    )
    if first != repeated or first == changed:
        raise SystemExit("ODD-004 snapshot identity is not exact-byte deterministic")

    runbook = repository_root / "docs" / "odd004-live-runbook.md"
    runbook_text = runbook.read_text(encoding="utf-8")
    required_official_urls = (
        "https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm",
        "https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_api.cfm",
        "https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_api.cfm",
        "https://dailymed.nlm.nih.gov/dailymed/spl-resources-all-drug-labels.cfm",
    )
    if any(url not in runbook_text for url in required_official_urls):
        raise SystemExit("ODD-004 runbook is missing a required official DailyMed URL")

    contract = {
        "batch_report_version": BATCH_REPORT_VERSION,
        "candidate_page_size": LIVE_PAGE_SIZE,
        "connector_version": CONNECTOR_VERSION,
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "document_type": HUMAN_PRESCRIPTION_DOCUMENT_CODE,
        "live_snapshot_version": LIVE_SNAPSHOT_VERSION,
        "package_version": __version__,
        "raw_manifest_version": RAW_MANIFEST_VERSION,
        "selection_rule_version": BATCH_SELECTION_RULE_VERSION,
        "tables": EXPECTED_TABLES,
    }
    digest = sha256_bytes(canonical_json_bytes(contract))
    if digest != EXPECTED_CONTRACT_SHA256:
        raise SystemExit(
            "ODD-004 live contract hash changed: "
            f"expected {EXPECTED_CONTRACT_SHA256}, got {digest}"
        )
    print(
        "ODD-004 live contract: OK "
        f"(schema={DATABASE_SCHEMA_VERSION}, snapshot={first}, sha256={digest})"
    )


if __name__ == "__main__":
    main()
