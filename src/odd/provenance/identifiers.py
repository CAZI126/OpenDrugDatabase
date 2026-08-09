"""Deterministic internal identifiers, separate from regulatory identifiers."""

from __future__ import annotations

from uuid import uuid5

from odd.constants import ODD_UUID_NAMESPACE
from odd.models import SourceIdentity
from odd.provenance.canonical import canonical_json_bytes


def source_record_id(identity: SourceIdentity) -> str:
    payload = {
        "authority": identity.authority,
        "jurisdiction": identity.jurisdiction,
        "provider": identity.provider,
        "raw_sha256": identity.raw_sha256,
        "source_document_id": identity.source_document_id,
        "source_version": identity.source_version,
    }
    return str(uuid5(ODD_UUID_NAMESPACE, canonical_json_bytes(payload).decode("utf-8")))


def regulatory_document_id(
    identity: SourceIdentity,
    *,
    parser_version: str,
    schema_version: str,
    mapping_version: str,
) -> str:
    name = "|".join(
        (
            source_record_id(identity),
            parser_version,
            schema_version,
            mapping_version,
        )
    )
    return str(uuid5(ODD_UUID_NAMESPACE, name))


def section_id(document_id: str, locator: str, section_sha256: str) -> str:
    return str(uuid5(ODD_UUID_NAMESPACE, f"section|{document_id}|{locator}|{section_sha256}"))


def product_id(
    document_id: str,
    sequence_index: int,
    brand_name: str | None,
    dosage_form: str | None,
    route: str | None,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "product",
                    document_id,
                    str(sequence_index),
                    brand_name or "",
                    dosage_form or "",
                    route or "",
                )
            ),
        )
    )


def ingredient_id(name: str) -> str:
    return str(uuid5(ODD_UUID_NAMESPACE, f"ingredient|{name.casefold()}"))


def mapping_id(section_identifier: str, concept: str, mapping_version: str) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            f"mapping|{section_identifier}|{concept}|{mapping_version}",
        )
    )


def document_lineage_id(
    authority: str,
    provider: str,
    jurisdiction: str,
    source_document_id: str,
) -> str:
    payload = canonical_json_bytes(
        {
            "authority": authority,
            "jurisdiction": jurisdiction,
            "provider": provider,
            "source_document_id": source_document_id,
        }
    ).decode("utf-8")
    return str(uuid5(ODD_UUID_NAMESPACE, f"lineage|{payload}"))


def history_snapshot_id(lineage_identifier: str, raw_sha256: str) -> str:
    return str(uuid5(ODD_UUID_NAMESPACE, f"history|{lineage_identifier}|{raw_sha256}"))


def version_edge_id(
    lineage_identifier: str,
    predecessor_document_id: str | None,
    successor_document_id: str | None,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "edge",
                    lineage_identifier,
                    predecessor_document_id or "",
                    successor_document_id or "",
                )
            ),
        )
    )


def document_diff_id(
    old_document_id: str | None,
    new_document_id: str | None,
    diff_engine_version: str,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "diff",
                    old_document_id or "",
                    new_document_id or "",
                    diff_engine_version,
                )
            ),
        )
    )


def section_diff_id(diff_identifier: str, sequence_index: int) -> str:
    return str(uuid5(ODD_UUID_NAMESPACE, f"section-diff|{diff_identifier}|{sequence_index}"))


def candidate_discovery_id(
    utilization_list_id: str,
    ingredient_identifier: str,
    connector_version: str,
    raw_metadata_sha256: str,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "candidate-discovery",
                    utilization_list_id,
                    ingredient_identifier,
                    connector_version,
                    raw_metadata_sha256,
                )
            ),
        )
    )


def live_candidate_snapshot_id(
    canonical_request: tuple[tuple[str, str], ...],
    page_hashes: tuple[tuple[int, str], ...],
    *,
    connector_version: str,
    terminal_fingerprint: str = "",
) -> str:
    """Identify one immutable live observation without operational timestamps."""

    payload = canonical_json_bytes(
        {
            "canonical_request": canonical_request,
            "connector_version": connector_version,
            "page_hashes": page_hashes,
            "terminal_fingerprint": terminal_fingerprint,
        }
    ).decode("utf-8")
    return str(uuid5(ODD_UUID_NAMESPACE, f"live-candidate-snapshot|{payload}"))


def live_batch_run_id(observation_token: str) -> str:
    """Create an operational run ID for one explicitly requested live observation."""

    return str(uuid5(ODD_UUID_NAMESPACE, f"live-batch-run|{observation_token}"))


def candidate_evidence_id(
    discovery_identifier: str,
    set_id: str,
    source_version: str,
    raw_metadata_sha256: str,
    occurrence_index: int,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "label-candidate",
                    discovery_identifier,
                    set_id.casefold(),
                    source_version,
                    raw_metadata_sha256,
                    str(occurrence_index),
                )
            ),
        )
    )


def candidate_decision_id(discovery_identifier: str, rule_version: str) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            f"candidate-decision|{discovery_identifier}|{rule_version}",
        )
    )


def batch_run_id(
    utilization_list_id: str,
    selection_rule_version: str,
    connector_version: str,
    parser_version: str,
    schema_version: str,
    mapping_version: str,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "batch-run",
                    utilization_list_id,
                    selection_rule_version,
                    connector_version,
                    parser_version,
                    schema_version,
                    mapping_version,
                )
            ),
        )
    )


def batch_artifact_id(
    batch_identifier: str,
    report_version: str,
    canonical_sha256: str,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            f"batch-artifact|{batch_identifier}|{report_version}|{canonical_sha256}",
        )
    )


def quarantine_record_id(
    batch_identifier: str,
    ingredient_identifier: str,
    stage: str,
    raw_sha256: str | None,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "quarantine",
                    batch_identifier,
                    ingredient_identifier,
                    stage,
                    raw_sha256 or "unknown",
                )
            ),
        )
    )


def enrichment_run_id(observation_token: str) -> str:
    return str(uuid5(ODD_UUID_NAMESPACE, f"enrichment-run|{observation_token}"))


def enrichment_execution_id(run_identifier: str, execution_token: str) -> str:
    return str(
        uuid5(ODD_UUID_NAMESPACE, f"enrichment-execution|{run_identifier}|{execution_token}")
    )


def enrichment_response_id(
    run_identifier: str,
    candidate_identifier: str,
    tier: str,
    page_number: int,
    request_identity: tuple[tuple[str, str], ...],
    raw_sha256: str | None,
    terminal_fingerprint: str = "",
) -> str:
    payload = canonical_json_bytes(
        {
            "candidate_id": candidate_identifier,
            "page_number": page_number,
            "raw_sha256": raw_sha256,
            "request_identity": request_identity,
            "run_id": run_identifier,
            "terminal_fingerprint": terminal_fingerprint,
            "tier": tier,
        }
    ).decode("utf-8")
    return str(uuid5(ODD_UUID_NAMESPACE, f"enrichment-response|{payload}"))


def enrichment_snapshot_id(
    parent_snapshots: tuple[tuple[int, str], ...],
    response_hashes: tuple[tuple[str, str], ...],
    assertion_identities: tuple[str, ...],
    *,
    extractor_version: str,
    extraction_rule_version: str,
) -> str:
    payload = canonical_json_bytes(
        {
            "assertion_identities": assertion_identities,
            "extraction_rule_version": extraction_rule_version,
            "extractor_version": extractor_version,
            "parent_snapshots": parent_snapshots,
            "response_hashes": response_hashes,
        }
    ).decode("utf-8")
    return str(uuid5(ODD_UUID_NAMESPACE, f"enrichment-snapshot|{payload}"))


def evidence_assertion_id(canonical_evidence_identity: str) -> str:
    return str(uuid5(ODD_UUID_NAMESPACE, f"evidence-assertion|{canonical_evidence_identity}"))


def evidence_identity(payload: dict[str, object]) -> str:
    canonical = canonical_json_bytes(payload).decode("utf-8")
    return str(uuid5(ODD_UUID_NAMESPACE, f"canonical-evidence|{canonical}"))


def enrichment_decision_revision_id(
    run_identifier: str,
    rank: int,
    snapshot_identifier: str,
    canonical_decision_sha256: str,
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            "|".join(
                (
                    "enrichment-decision-revision",
                    run_identifier,
                    str(rank),
                    snapshot_identifier,
                    canonical_decision_sha256,
                )
            ),
        )
    )


def enrichment_artifact_id(
    run_identifier: str, report_version: str, canonical_sha256: str
) -> str:
    return str(
        uuid5(
            ODD_UUID_NAMESPACE,
            f"enrichment-artifact|{run_identifier}|{report_version}|{canonical_sha256}",
        )
    )
