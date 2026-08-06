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
