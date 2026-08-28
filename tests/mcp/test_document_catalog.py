"""Catalog construction, integrity, and MCP discovery contract tests."""

from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from odd.catalog import (
    CATALOG_FRESHNESS_NOT_CHECKED,
    CATALOG_INVALID,
    CATALOG_NOT_BUILT,
    CATALOG_SCHEMA_UNSUPPORTED,
    CatalogError,
    build_document_catalog,
    verify_document_catalog,
)
from odd.core.cli import main as core_main
from odd.core.direct import fetch_by_set_id
from odd.core.evidence import LABEL_PUBLISHER, LABEL_REPOSITORY, UNKNOWN
from odd.errors import ODDError
from odd.mcp.tools import OddTools, ToolError
from odd.provenance.canonical import canonical_json_bytes
from odd.provenance.hashing import sha256_bytes
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_XML, pipeline
from tests.mcp.test_offline import forbid_network, tree

V29_XML = Path("tests/fixtures/dailymed/history/apixaban_eliquis_v29.xml")
SECOND_SET_ID = "aaaaaaaa-0000-4000-8000-00000000000a"
QUERIES = (
    "apixaban",
    "Eliquis",
    "APIXABAN",
    "pixab",
    "apixaban tablet",
    "a drug no preserved label mentions",
)


def _multi_document_pipeline(tmp_path: Path) -> Any:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)

    historic = pipeline(tmp_path, xml_body=V29_XML.read_bytes())
    fetch_by_set_id(historic.connector, historic.raw_store, ELIQUIS_SET_ID)

    twin_xml = ELIQUIS_XML.read_bytes().replace(
        ELIQUIS_SET_ID.encode(), SECOND_SET_ID.encode()
    )
    twin = pipeline(tmp_path, xml_body=twin_xml)
    fetch_by_set_id(twin.connector, twin.raw_store, SECOND_SET_ID)
    return core


def _single_document_pipeline(tmp_path: Path) -> Any:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    return core


def _legacy_candidates(core: Any, query: str) -> list[dict[str, Any]]:
    """The pre-catalog scan contract, retained only as a fixture oracle."""

    wanted = query.strip().casefold()
    candidates: list[dict[str, Any]] = []
    root = core.raw_store.root / "dailymed"
    for set_directory in sorted(root.iterdir()):
        if not set_directory.is_dir():
            continue
        for version_directory in sorted(set_directory.iterdir()):
            if not (version_directory / "label.xml").is_file():
                continue
            try:
                raw = core.raw_store.resolve(set_directory.name, version_directory.name)
                normalized = core.parser.parse(raw.label_path.read_bytes(), raw.identity)
            except ODDError:
                continue
            document = normalized.document
            fields = [
                document.title or "",
                document.generic_name or "",
                *document.brand_names,
                *document.active_ingredients,
            ]
            if not any(wanted in value.casefold() for value in fields):
                continue
            identity = raw.identity
            candidates.append(
                {
                    "set_id": identity.source_document_id,
                    "source_version": identity.source_version,
                    "document_title": document.title or UNKNOWN,
                    "brand_names": list(document.brand_names) or UNKNOWN,
                    "generic_name": document.generic_name or UNKNOWN,
                    "active_ingredients": list(document.active_ingredients) or UNKNOWN,
                    "effective_date": (
                        document.effective_date.isoformat()
                        if document.effective_date is not None
                        else UNKNOWN
                    ),
                    "document_type": document.document_type or UNKNOWN,
                    "label_publisher": LABEL_PUBLISHER,
                    "label_repository": LABEL_REPOSITORY,
                    "regulatory_recipient": identity.authority,
                    "jurisdiction": identity.jurisdiction,
                    "fda_approval_status": UNKNOWN,
                    "source_url": identity.source_url or UNKNOWN,
                    "raw_sha256": identity.raw_sha256,
                    "raw_path": raw.label_path.resolve().relative_to(
                        core.data_root.resolve()
                    ).as_posix(),
                    "matched_query": query,
                }
            )
    return candidates


def _catalog_paths(data_root: Path) -> tuple[Path, Path]:
    directory = data_root / "catalog"
    return directory / "documents.jsonl", directory / "manifest.json"


def _read_manifest(data_root: Path) -> dict[str, Any]:
    _documents, manifest = _catalog_paths(data_root)
    return json.loads(manifest.read_bytes())


def _write_manifest(data_root: Path, manifest: dict[str, Any]) -> None:
    _documents, path = _catalog_paths(data_root)
    path.write_bytes(canonical_json_bytes(manifest) + b"\n")


def _replace_documents(
    data_root: Path, content: bytes, *, record_count: int | None = None
) -> None:
    documents, _manifest_path = _catalog_paths(data_root)
    documents.write_bytes(content)
    manifest = _read_manifest(data_root)
    manifest["catalog_bytes"] = len(content)
    manifest["catalog_sha256"] = sha256_bytes(content)
    if record_count is not None:
        manifest["indexed_count"] = record_count
        manifest["record_count"] = record_count
        manifest["source_document_count"] = record_count + int(
            manifest["unindexed_count"]
        )
    _write_manifest(data_root, manifest)


def _tool_error(surface: OddTools, query: str = "apixaban") -> ToolError:
    with pytest.raises(ToolError) as caught:
        surface.find_documents(query)
    return caught.value


def test_catalog_search_is_identical_to_the_old_scan_contract(tmp_path: Path) -> None:
    core = _multi_document_pipeline(tmp_path)
    old = {query: _legacy_candidates(core, query) for query in QUERIES}

    built = build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    surface = OddTools(core)

    assert built["source_document_count"] == 3
    assert built["indexed_count"] == 3
    for query in QUERIES:
        found = surface.find_documents(query)
        assert found["candidates"] == old[query]
        assert found["candidate_count"] == len(old[query])
        assert found["selection_performed"] is False
    assert [
        (candidate["set_id"], candidate["source_version"])
        for candidate in surface.find_documents("apixaban")["candidates"]
    ] == [
        (SECOND_SET_ID, "30"),
        (ELIQUIS_SET_ID, "29"),
        (ELIQUIS_SET_ID, "30"),
    ]

    blank = _tool_error(surface, "   ")
    assert blank.as_dict() == {
        "status": "error",
        "error": {
            "code": "BLANK_QUERY",
            "details": {},
            "message": "a query is required to find preserved documents",
        },
    }


def test_find_uses_no_xml_parser_after_catalog_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("an XML parser was called during catalog search")

    monkeypatch.setattr(core.parser, "parse", fail)
    monkeypatch.setattr(core.parser, "parse_document_search_metadata", fail)
    monkeypatch.setattr("odd.parsers.spl.parser.ElementTree.fromstring", fail)

    found = OddTools(core).find_documents("apixaban")

    assert found["candidate_count"] == 1


def test_find_is_offline_read_only_and_makes_no_freshness_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    surface = OddTools(core)
    attempts = forbid_network(monkeypatch)
    before = tree(core.data_root)

    found = surface.find_documents("apixaban")

    after = tree(core.data_root)
    assert attempts == []
    assert after == before
    assert found["catalog_freshness"] == CATALOG_FRESHNESS_NOT_CHECKED
    assert found["catalog_built_from_fingerprint"]
    assert found["selection_performed"] is False


def test_missing_catalog_and_blank_query_have_stable_structured_errors(
    tmp_path: Path,
) -> None:
    surface = OddTools(pipeline(tmp_path))

    missing = _tool_error(surface)
    assert missing.code == CATALOG_NOT_BUILT
    assert "odd catalog build" in missing.message
    assert _tool_error(surface, " ").code == "BLANK_QUERY"


def test_invalid_catalog_json_is_a_structured_error(tmp_path: Path) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    _replace_documents(core.data_root, b"{not-json}\n", record_count=1)

    assert _tool_error(OddTools(core)).code == CATALOG_INVALID


def test_catalog_digest_mismatch_is_a_structured_error(tmp_path: Path) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    documents, _manifest = _catalog_paths(core.data_root)
    original = documents.read_bytes()
    changed = original.replace(b"ELIQUIS", b"ELIQUIs", 1)
    assert len(changed) == len(original) and changed != original
    documents.write_bytes(changed)

    error = _tool_error(OddTools(core))
    assert error.code == CATALOG_INVALID
    assert "SHA-256" in error.message


def test_unsupported_catalog_schema_is_a_structured_error(tmp_path: Path) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    manifest = _read_manifest(core.data_root)
    manifest["schema_version"] = "odd-document-catalog/999.0.0"
    _write_manifest(core.data_root, manifest)

    assert _tool_error(OddTools(core)).code == CATALOG_SCHEMA_UNSUPPORTED


def test_duplicate_raw_record_is_a_structured_error(tmp_path: Path) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    documents, _manifest = _catalog_paths(core.data_root)
    first = documents.read_bytes()
    _replace_documents(core.data_root, first + first, record_count=2)

    error = _tool_error(OddTools(core))
    assert error.code == CATALOG_INVALID
    assert "duplicate raw document" in error.message


def test_verify_checks_order_and_raw_manifest_correspondence(tmp_path: Path) -> None:
    core = _multi_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    documents, _manifest = _catalog_paths(core.data_root)
    lines = documents.read_bytes().splitlines(keepends=True)
    _replace_documents(core.data_root, b"".join(reversed(lines)), record_count=3)

    with pytest.raises(CatalogError) as unordered:
        verify_document_catalog(core.data_root)
    assert unordered.value.code == CATALOG_INVALID
    assert "canonical storage order" in unordered.value.message

    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    records = [json.loads(line) for line in documents.read_bytes().splitlines()]
    records[0]["raw_sha256"] = "0" * 64
    changed = b"".join(canonical_json_bytes(record) + b"\n" for record in records)
    _replace_documents(core.data_root, changed, record_count=3)
    with pytest.raises(CatalogError) as mismatched:
        verify_document_catalog(core.data_root)
    assert mismatched.value.code == CATALOG_INVALID
    assert "raw SHA-256 differs" in mismatched.value.message


def test_verify_is_complete_without_parsing_xml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("verify parsed an XML document")

    monkeypatch.setattr("odd.parsers.spl.parser.ElementTree.fromstring", fail)
    verified = verify_document_catalog(core.data_root)

    assert verified["result"] == "VERIFIED"
    assert verified["xml_documents_parsed"] == 0


def test_repeated_builds_have_deterministic_content_and_fingerprint(
    tmp_path: Path,
) -> None:
    core = _multi_document_pipeline(tmp_path)
    first = build_document_catalog(
        core.data_root,
        parser=core.parser,
        clock=lambda: datetime(2026, 8, 28, 1, tzinfo=UTC),
    )
    documents, _manifest_path = _catalog_paths(core.data_root)
    first_documents = documents.read_bytes()
    first_manifest = _read_manifest(core.data_root)

    second = build_document_catalog(
        core.data_root,
        parser=core.parser,
        clock=lambda: datetime(2026, 8, 28, 2, tzinfo=UTC),
    )
    second_manifest = _read_manifest(core.data_root)

    assert documents.read_bytes() == first_documents
    assert second["catalog_sha256"] == first["catalog_sha256"]
    assert second["source_identity_fingerprint"] == first[
        "source_identity_fingerprint"
    ]
    first_manifest.pop("built_at")
    second_manifest.pop("built_at")
    assert second_manifest == first_manifest


def test_build_prefers_preserved_normalized_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _single_document_pipeline(tmp_path)
    core.extract(ELIQUIS_SET_ID, "30")

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("raw XML was parsed despite preserved evidence")

    monkeypatch.setattr(core.parser, "parse_document_search_metadata", fail)
    built = build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)

    assert built["indexed_count"] == 1
    assert built["metadata_source_counts"] == {
        "preserved_evidence": 1,
        "preserved_raw": 0,
    }


def test_title_missing_document_is_explicitly_unindexed_without_guessing(
    tmp_path: Path,
) -> None:
    xml = ELIQUIS_XML.read_bytes()
    without_title = re.sub(br"\s*<title>.*?</title>", b"", xml, count=1)
    assert without_title != xml
    core = pipeline(tmp_path, xml_body=without_title)
    fetch_by_set_id(core.connector, core.raw_store, ELIQUIS_SET_ID)

    built = build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)

    assert built["source_document_count"] == 1
    assert built["indexed_count"] == 0
    assert built["unindexed_count"] == 1
    reason = built["unindexed"][0]
    assert reason["set_id"] == ELIQUIS_SET_ID
    assert reason["raw_sha256"]
    assert reason["reason_code"] == "UNSUPPORTED_DOCUMENT_STRUCTURE"
    assert OddTools(core).find_documents("apixaban")["candidate_count"] == 0


def test_catalog_cli_builds_and_verifies_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _single_document_pipeline(tmp_path)
    attempts = forbid_network(monkeypatch)
    build_output = io.StringIO()
    verify_output = io.StringIO()

    build_code = core_main(
        ["catalog", "build", "--data-dir", str(core.data_root)], stream=build_output
    )
    verify_code = core_main(
        ["catalog", "verify", "--data-dir", str(core.data_root)], stream=verify_output
    )

    assert build_code == verify_code == 0
    assert json.loads(build_output.getvalue())["result"] == "BUILT"
    assert json.loads(verify_output.getvalue())["result"] == "VERIFIED"
    assert attempts == []


def test_catalog_manifest_marks_itself_as_rebuildable_derivative(tmp_path: Path) -> None:
    core = _single_document_pipeline(tmp_path)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    manifest = _read_manifest(core.data_root)

    assert manifest["primary_source"] is False
    assert "rebuildable derived search index" in manifest["derivation_note"]
    assert not list((core.data_root / "catalog").glob("*.tmp"))
