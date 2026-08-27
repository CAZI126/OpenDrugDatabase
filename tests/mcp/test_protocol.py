"""The Eliquis vertical slice, driven through the real MCP protocol.

These are not calls into Python functions. A client session is connected to the
server over the SDK's own transport, so initialize, tools/list, and tools/call
all go through the protocol the way an AI client would drive them.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session

from odd.mcp.server import TOOL_DEFINITIONS, create_server
from odd.mcp.tools import OddTools
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline
from tests.core.test_drugsfda import (
    archive_bytes,
    preserve_fixture_archive,
    spl_with_application,
)

APPLICATION = "NDA202155"
EXPECTED_TOOLS = [
    "odd_find_documents",
    "odd_get_section_index",
    "odd_get_evidence_slice",
    "odd_verify_document",
]


def surface(
    tmp_path: Path, *, with_application: bool = False, archive: bytes | None = None
) -> OddTools:
    core = pipeline(
        tmp_path, xml_body=spl_with_application() if with_application else None
    )
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    if archive is not None:
        preserve_fixture_archive(core, archive)
    return OddTools(core)


def session(tools: OddTools) -> Any:
    return create_connected_server_and_client_session(create_server(tools=tools))


async def call(client: Any, name: str, **arguments: Any) -> dict[str, Any]:
    """One tools/call round trip, decoded from the text content it returns."""

    result = await client.call_tool(name, arguments)
    assert result.content, f"{name} returned no content"
    return json.loads(result.content[0].text)


def drive(tools: OddTools, body: Callable[[Any], Any]) -> Any:
    import anyio

    async def run() -> Any:
        async with session(tools) as client:
            await client.initialize()
            return await body(client)

    return anyio.run(run)


def test_initialize_and_tools_list_advertise_the_four_tools(tmp_path: Path) -> None:
    async def body(client: Any) -> list[str]:
        listed = await client.list_tools()
        return [tool.name for tool in listed.tools]

    assert drive(surface(tmp_path), body) == EXPECTED_TOOLS
    assert [tool.name for tool in TOOL_DEFINITIONS] == EXPECTED_TOOLS


def test_every_advertised_tool_declares_its_required_arguments() -> None:
    required = {tool.name: tool.inputSchema.get("required", []) for tool in TOOL_DEFINITIONS}

    assert required["odd_find_documents"] == ["query"]
    assert required["odd_get_section_index"] == ["set_id"]
    assert required["odd_get_evidence_slice"] == ["set_id", "section_codes"]
    assert required["odd_verify_document"] == ["set_id"]


def test_the_whole_eliquis_question_runs_end_to_end_over_the_protocol(
    tmp_path: Path,
) -> None:
    """Find the document, read its index, take two sections, link FDA, verify."""

    tools = surface(tmp_path, with_application=True, archive=archive_bytes())
    expected_sha = tools.pipeline.raw_store.resolve(
        ELIQUIS_SET_ID, ELIQUIS_VERSION
    ).identity.raw_sha256

    async def body(client: Any) -> dict[str, Any]:
        found = await call(client, "odd_find_documents", query="apixaban")
        set_id = found["candidates"][0]["set_id"]
        index = await call(client, "odd_get_section_index", set_id=set_id)
        present = [
            entry["section_code"]
            for entry in index["sections"]
            if entry["content_status"] == "present"
        ]
        wanted = [present[0], next(c for c in present if c != present[0])]
        piece = await call(
            client,
            "odd_get_evidence_slice",
            set_id=set_id,
            section_codes=wanted,
            application_number=APPLICATION,
        )
        verified = await call(client, "odd_verify_document", set_id=set_id)
        return {
            "found": found,
            "index": index,
            "requested": wanted,
            "slice": piece,
            "verify": verified,
        }

    out = drive(tools, body)

    # 1. the document was identified, with provenance intact
    candidate = out["found"]["candidates"][0]
    assert candidate["set_id"] == ELIQUIS_SET_ID
    assert candidate["source_version"] == ELIQUIS_VERSION
    assert candidate["raw_sha256"] == expected_sha
    assert candidate["source_url"].endswith(f"/spls/{ELIQUIS_SET_ID}.xml")
    assert candidate["effective_date"] != "UNKNOWN"

    # 2. the index describes the document and carries none of its text
    index = out["index"]
    assert index["section_count"] > 0
    assert index["carries_section_text"] is False
    assert all("text" not in entry for entry in index["sections"])
    assert "ELIQUIS is indicated" not in json.dumps(index)

    # 3. the slice carries only what was named
    piece, requested = out["slice"], out["requested"]
    assert sorted(piece["returned_section_codes"]) == sorted(requested)
    assert piece["unexpected_section_codes"] == []
    assert piece["subsections_added_implicitly"] is False
    assert piece["document"]["raw_sha256"] == expected_sha
    assert piece["document"]["source_version"] == ELIQUIS_VERSION
    assert piece["document"]["effective_date"] != "UNKNOWN"
    for section in piece["sections"]:
        assert section["text"]
        assert section["evidence"]["xml_locator"]
        assert section["evidence"]["section_sha256"]
        assert section["evidence"]["raw_sha256"] == expected_sha

    # 4. Drugs@FDA reached by exact application identity
    fda = piece["drugs_fda"]
    assert fda["requested_application_number"] == APPLICATION
    assert fda["status"] == "EXACT"
    assert [s["application_number"] for s in fda["sources"]] == [APPLICATION]

    # 5. re-verification against the preserved bytes
    verify = out["verify"]
    assert verify["result"] == "VERIFIED"
    assert verify["raw_bytes_sha256"]["observed"] == "VERIFIED"
    assert verify["section_anchors"]["observed"] == "VERIFIED"
    assert expected_sha in verify["raw_bytes_sha256"]["message"]
    assert verify["failure_reasons"] == []


def test_a_section_code_the_document_lacks_is_not_invented_over_the_protocol(
    tmp_path: Path,
) -> None:
    tools = surface(tmp_path)

    async def body(client: Any) -> dict[str, Any]:
        index = await call(client, "odd_get_section_index", set_id=ELIQUIS_SET_ID)
        present = next(
            e["section_code"] for e in index["sections"] if e["content_status"] == "present"
        )
        return await call(
            client,
            "odd_get_evidence_slice",
            set_id=ELIQUIS_SET_ID,
            section_codes=[present, "00000-0"],
        )

    piece = drive(tools, body)

    assert piece["section_codes_not_found"] == ["00000-0"]
    assert "00000-0" not in piece["returned_section_codes"]
    assert len(piece["sections"]) == 1


def test_an_unpreserved_identity_returns_a_structured_error_not_a_crash(
    tmp_path: Path,
) -> None:
    async def body(client: Any) -> dict[str, Any]:
        return await call(
            client,
            "odd_get_section_index",
            set_id="00000000-0000-4000-8000-000000000000",
        )

    payload = drive(surface(tmp_path), body)

    assert payload["status"] == "error"
    assert payload["error"]["code"] == "NOT_PRESERVED"
    assert payload["error"]["message"]


def test_an_unknown_tool_name_returns_a_structured_error(tmp_path: Path) -> None:
    async def body(client: Any) -> Any:
        return await client.call_tool("odd_not_a_tool", {})

    result = drive(surface(tmp_path), body)
    payload = json.loads(result.content[0].text)

    assert payload["status"] == "error"
    assert payload["error"]["code"] in {"UNKNOWN_TOOL", "INTERNAL_ERROR"}


def test_the_same_protocol_call_twice_returns_the_same_payload(tmp_path: Path) -> None:
    tools = surface(tmp_path)

    async def body(client: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        first = await call(client, "odd_get_section_index", set_id=ELIQUIS_SET_ID)
        second = await call(client, "odd_get_section_index", set_id=ELIQUIS_SET_ID)
        return first, second

    first, second = drive(tools, body)
    assert first == second
