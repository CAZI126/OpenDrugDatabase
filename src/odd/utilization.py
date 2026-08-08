"""Versioned, non-regulatory utilization-list loading and validation."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any, cast

from odd.constants import UTILIZATION_LIST_SCHEMA_VERSION
from odd.errors import UtilizationInputInvalid
from odd.models import (
    IngredientIdentity,
    IngredientIdentityStatus,
    UtilizationEntry,
    UtilizationList,
)
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.identifiers import ingredient_id

DEFAULT_UTILIZATION_LIST_ID = "us-top10-2023"
_RESOURCE_NAMES = {DEFAULT_UTILIZATION_LIST_ID: "resources/us_top10_2023.json"}
_WHITESPACE = re.compile(r"\s+")


def available_utilization_lists() -> tuple[UtilizationList, ...]:
    return tuple(load_utilization_list(identifier) for identifier in sorted(_RESOURCE_NAMES))


def load_utilization_list(list_id: str = DEFAULT_UTILIZATION_LIST_ID) -> UtilizationList:
    resource_name = _RESOURCE_NAMES.get(list_id)
    if resource_name is None:
        raise UtilizationInputInvalid(
            "utilization list is not available",
            details={"available_lists": sorted(_RESOURCE_NAMES), "utilization_list_id": list_id},
        )
    try:
        raw = files("odd").joinpath(resource_name).read_bytes()
        decoded = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UtilizationInputInvalid(f"utilization list could not be read: {exc}") from exc
    if not isinstance(decoded, dict):
        raise UtilizationInputInvalid("utilization list must be a JSON object")
    return utilization_list_from_payload(cast(dict[str, Any], decoded))


def utilization_list_from_payload(payload: dict[str, Any]) -> UtilizationList:
    list_id = _required_text(payload, "utilization_list_id")
    schema_version = _required_text(payload, "schema_version")
    if schema_version != UTILIZATION_LIST_SCHEMA_VERSION:
        raise UtilizationInputInvalid(
            "unsupported utilization-list schema version",
            details={"schema_version": schema_version},
        )
    measurement_year = payload.get("measurement_year")
    if isinstance(measurement_year, bool) or not isinstance(measurement_year, int):
        raise UtilizationInputInvalid("measurement_year must be an integer")
    retrieved_at = _datetime(payload.get("retrieved_at"))
    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise UtilizationInputInvalid("utilization entries must be a non-empty array")

    entries: list[UtilizationEntry] = []
    ranks: set[int] = set()
    ingredients: set[str] = set()
    for index, value in enumerate(raw_entries):
        if not isinstance(value, dict):
            raise UtilizationInputInvalid(
                "utilization entry must be an object", details={"entry_index": index}
            )
        item = cast(dict[str, Any], value)
        rank = item.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank < 1:
            raise UtilizationInputInvalid(
                "utilization rank must be a positive integer", details={"entry_index": index}
            )
        name = _required_text(item, "ingredient_name")
        normalized = normalize_ingredient_name(name)
        if rank in ranks:
            raise UtilizationInputInvalid("duplicate utilization rank", details={"rank": rank})
        if normalized in ingredients:
            raise UtilizationInputInvalid(
                "duplicate normalized utilization ingredient",
                details={"normalized_ingredient_name": normalized},
            )
        metric_value = item.get("metric_value")
        if isinstance(metric_value, bool) or (
            metric_value is not None and not isinstance(metric_value, (int, float))
        ):
            raise UtilizationInputInvalid("metric_value must be numeric or null")
        ranks.add(rank)
        ingredients.add(normalized)
        entries.append(
            UtilizationEntry(
                utilization_list_id=list_id,
                rank=rank,
                ingredient_name=name,
                normalized_ingredient_name=normalized,
                metric_value=float(metric_value) if metric_value is not None else None,
                metric_unit=_optional_text(item, "metric_unit"),
                source_row_identifier=_optional_text(item, "source_row_identifier"),
            )
        )

    ordered = tuple(sorted(entries, key=lambda entry: entry.rank))
    expected_ranks = tuple(range(1, len(ordered) + 1))
    if tuple(item.rank for item in ordered) != expected_ranks:
        raise UtilizationInputInvalid(
            "utilization ranks must be contiguous from one",
            details={"actual_ranks": [item.rank for item in ordered]},
        )
    return UtilizationList(
        utilization_list_id=list_id,
        schema_version=schema_version,
        jurisdiction=_required_text(payload, "jurisdiction"),
        dataset_name=_required_text(payload, "dataset_name"),
        dataset_version=_required_text(payload, "dataset_version"),
        measurement_year=measurement_year,
        metric=_required_text(payload, "metric"),
        source_reference=_required_text(payload, "source_reference"),
        retrieved_at=retrieved_at,
        license_or_terms_status=_required_text(payload, "license_or_terms_status"),
        source_status=_required_text(payload, "source_status"),
        notes=_required_text(payload, "notes"),
        entries=ordered,
    )


def canonical_utilization_list_bytes(value: UtilizationList) -> bytes:
    return canonical_json_bytes(value)


def ingredient_identity(entry: UtilizationEntry) -> IngredientIdentity:
    normalized = normalize_ingredient_name(entry.ingredient_name)
    status = (
        IngredientIdentityStatus.EXACT_NAME
        if entry.ingredient_name == normalized
        else IngredientIdentityStatus.NORMALIZED_NAME
    )
    return IngredientIdentity(
        original_ranked_ingredient=entry.ingredient_name,
        normalized_search_string=normalized,
        ingredient_id=ingredient_id(normalized),
        synonyms_used=(),
        salt_or_form_qualifiers=(),
        identity_status=status,
    )


def normalize_ingredient_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return _WHITESPACE.sub(" ", normalized).strip()


def _required_text(payload: dict[str, Any], name: str) -> str:
    value = payload.get(name)
    if not isinstance(value, str) or not value.strip():
        raise UtilizationInputInvalid(f"{name} must be non-empty text")
    return value.strip()


def _optional_text(payload: dict[str, Any], name: str) -> str | None:
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise UtilizationInputInvalid(f"{name} must be text or null")
    return value.strip() or None


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise UtilizationInputInvalid("retrieved_at must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise UtilizationInputInvalid("retrieved_at must be an ISO-8601 timestamp") from exc
    aware = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return aware.astimezone(UTC)
