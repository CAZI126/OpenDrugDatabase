"""Independently verify the versioned ODD-005 enrichment contract offline."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from odd import __version__
from odd.constants import (
    CONNECTOR_VERSION,
    ENRICHMENT_EXTRACTOR_VERSION,
    ENRICHMENT_REPORT_VERSION,
    ENRICHMENT_RULE_VERSION,
    ENRICHMENT_SELECTION_RULE_VERSION,
    ENRICHMENT_SNAPSHOT_VERSION,
)
from odd.models.enrichment import EvidenceResult, EvidenceType
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from odd.provenance.identifiers import enrichment_snapshot_id
from odd.storage.sqlite import DATABASE_SCHEMA_VERSION, SQLiteRepository

EXPECTED_TABLES = (
    "decision_revisions",
    "detail_response_evidence",
    "enrichment_artifacts",
    "enrichment_executions",
    "enrichment_item_states",
    "enrichment_run_snapshots",
    "enrichment_runs",
    "enrichment_snapshot_assertions",
    "enrichment_snapshots",
    "evidence_assertions",
)
EXPECTED_CONTRACT_SHA256 = "c7f1a4708801104b48373667fc9274cec1eb8059bc466e4e77dc067b5917d126"


def main() -> None:
    if __version__ != "0.5.0":
        raise SystemExit(f"ODD package version is {__version__}, expected 0.5.0")
    repository_root = Path(__file__).resolve().parents[1]
    temporary_root = repository_root / ".tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="odd005-contract-", dir=temporary_root) as temporary:
        repository = SQLiteRepository(Path(temporary) / "contract.sqlite3")
        repository.initialize_schema()
        if repository.schema_versions() != ("1", "2", "3", "4", "5"):
            raise SystemExit(f"unexpected migrations: {repository.schema_versions()}")
        for table in EXPECTED_TABLES:
            repository.table_count(table)

    parent_snapshots = ((1, "parent-snapshot"),)
    first_responses = tuple(sorted((("response-b", "b" * 64), ("response-a", "a" * 64))))
    reordered_responses = tuple(
        sorted((("response-a", "a" * 64), ("response-b", "b" * 64)))
    )
    assertions = tuple(sorted(("assertion-b", "assertion-a")))
    first = enrichment_snapshot_id(
        parent_snapshots,
        first_responses,
        assertions,
        extractor_version=ENRICHMENT_EXTRACTOR_VERSION,
        extraction_rule_version=ENRICHMENT_RULE_VERSION,
    )
    reordered = enrichment_snapshot_id(
        parent_snapshots,
        reordered_responses,
        assertions,
        extractor_version=ENRICHMENT_EXTRACTOR_VERSION,
        extraction_rule_version=ENRICHMENT_RULE_VERSION,
    )
    changed = enrichment_snapshot_id(
        parent_snapshots,
        tuple(sorted((("response-a", "a" * 64), ("response-b", "c" * 64)))),
        assertions,
        extractor_version=ENRICHMENT_EXTRACTOR_VERSION,
        extraction_rule_version=ENRICHMENT_RULE_VERSION,
    )
    if first != reordered or first == changed:
        raise SystemExit("ODD-005 snapshot identity is not exact-byte deterministic")

    runbook = repository_root / "docs" / "odd005-enrichment-runbook.md"
    runbook_text = runbook.read_text(encoding="utf-8")
    required_official_urls = (
        "https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm",
        "https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_packaging_api.cfm",
        "https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_api.cfm",
        "https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_history_api.cfm",
        "https://www.fda.gov/media/84201/download?attachment=",
        "https://www.fda.gov/industry/structured-product-labeling-resources/business-operation",
    )
    if any(url not in runbook_text for url in required_official_urls):
        raise SystemExit("ODD-005 runbook is missing a required official URL")

    contract = {
        "connector_version": CONNECTOR_VERSION,
        "database_schema_version": DATABASE_SCHEMA_VERSION,
        "evidence_results": tuple(value.value for value in EvidenceResult),
        "evidence_types": tuple(value.value for value in EvidenceType),
        "extractor_version": ENRICHMENT_EXTRACTOR_VERSION,
        "package_version": __version__,
        "report_version": ENRICHMENT_REPORT_VERSION,
        "rule_version": ENRICHMENT_RULE_VERSION,
        "selection_rule_version": ENRICHMENT_SELECTION_RULE_VERSION,
        "snapshot_version": ENRICHMENT_SNAPSHOT_VERSION,
        "tables": EXPECTED_TABLES,
    }
    digest = sha256_bytes(canonical_json_bytes(contract))
    if digest != EXPECTED_CONTRACT_SHA256:
        raise SystemExit(
            "ODD-005 enrichment contract hash changed: "
            f"expected {EXPECTED_CONTRACT_SHA256}, got {digest}"
        )
    print(
        "ODD-005 enrichment contract: OK "
        f"(schema={DATABASE_SCHEMA_VERSION}, snapshot={first}, sha256={digest})"
    )


if __name__ == "__main__":
    main()
