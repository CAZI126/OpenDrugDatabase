"""The MCP surface reads, and only reads.

Every test here runs with the network refused at the socket, so a tool that tries
to retrieve anything fails loudly instead of quietly succeeding on a machine that
happens to be online. Each one also compares the whole data root, file by file
and digest by digest, before and after the call: a reader that leaves a new
artifact behind has changed the thing it was asked to describe.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path
from typing import Any

import pytest

from odd.mcp.tools import OddTools
from odd.provenance.hashing import sha256_file
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_VERSION, pipeline
from tests.core.test_drugsfda import (
    archive_bytes,
    preserve_fixture_archive,
    spl_with_application,
)

APPLICATION = "NDA202155"
NOT_THIS_APPLICATION = ("202155", "NDA2021", "nda", "NDA999999")


LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def forbid_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Refuse every connection off this machine and record that it was attempted.

    Loopback stays open: an event loop wakes itself through a local socket pair,
    which is not a retrieval and must not be mistaken for one. Nothing ODD
    retrieves lives on this machine, so refusing everything else is enough.
    """

    attempts: list[str] = []
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex

    def host_of(address: Any) -> str:
        return str(address[0]) if isinstance(address, tuple) and address else str(address)

    def refuse(self: Any, address: Any, *args: Any, **kwargs: Any) -> Any:
        if host_of(address) in LOOPBACK:
            return connect(self, address, *args, **kwargs)
        attempts.append(str(address))
        raise AssertionError(f"an offline tool attempted to reach {address}")

    def refuse_ex(self: Any, address: Any, *args: Any, **kwargs: Any) -> Any:
        if host_of(address) in LOOPBACK:
            return connect_ex(self, address, *args, **kwargs)
        attempts.append(str(address))
        raise AssertionError(f"an offline tool attempted to reach {address}")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse_ex)

    def refuse_download(*args: Any, **kwargs: Any) -> None:
        attempts.append("drugsfda download")
        raise AssertionError("an offline tool attempted a Drugs@FDA download")

    # Named as well as socket-level, so the failure says which promise broke.
    monkeypatch.setattr("odd.core.pipeline.resolve_download", refuse_download)
    monkeypatch.setattr("odd.core.pipeline.retrieve_archive", refuse_download)
    return attempts


def tree(root: Path) -> dict[str, str]:
    """Every file under the data root with the digest of its bytes."""

    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def surface(tmp_path: Path, *, archive: bytes | None = None) -> OddTools:
    core = pipeline(tmp_path, xml_body=spl_with_application())
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    if archive is not None:
        preserve_fixture_archive(core, archive)
    return OddTools(core)


def a_present_code(tools: OddTools) -> str:
    index = tools.get_section_index(ELIQUIS_SET_ID)
    return next(
        entry["section_code"]
        for entry in index["sections"]
        if entry["content_status"] == "present"
    )


# -- the archive is preserved ----------------------------------------------
def test_a_preserved_archive_answers_the_slice_without_reaching_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path, archive=archive_bytes())
    code = a_present_code(tools)
    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, [code], APPLICATION)

    fda = result["drugs_fda"]
    assert fda["status"] == "EXACT"
    assert fda["requested_application_number"] == APPLICATION
    assert fda["network_attempted"] is False
    source = fda["sources"][0]
    assert source["application_number"] == APPLICATION
    assert source["archive"]["raw_sha256"]
    rows = source["link"]["fda_evidence"]["rows"]
    assert rows
    for row in rows:
        assert row["zip_member"] and isinstance(row["row_number"], int) and row["row_sha256"]
    assert attempts == []
    assert tree(tools.pipeline.data_root) == before


def test_the_preserved_archive_is_read_by_exact_identity_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The archive is there, so a number it does not name is NOT_FOUND, not absent."""

    tools = surface(tmp_path, archive=archive_bytes())
    code = a_present_code(tools)
    attempts = forbid_network(monkeypatch)

    for requested in NOT_THIS_APPLICATION:
        result = tools.get_evidence_slice(ELIQUIS_SET_ID, [code], requested)

        assert result["drugs_fda"]["sources"] == [], requested
        assert result["drugs_fda"]["status"] == "NOT_FOUND", requested
        assert result["drugs_fda"]["network_attempted"] is False
    assert attempts == []


# -- the archive is not preserved ------------------------------------------
def test_without_an_archive_the_sections_still_come_back_and_fda_is_not_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Nothing to read is a different answer from reading and finding nothing."""

    tools = surface(tmp_path)
    code = a_present_code(tools)
    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, [code], APPLICATION)

    assert result["returned_section_codes"] == [code]
    assert result["sections"][0]["text"]
    fda = result["drugs_fda"]
    assert fda["status"] == "NOT_PRESERVED"
    assert fda["status"] != "NOT_FOUND"
    assert fda["sources"] == []
    assert fda["network_attempted"] is False
    assert "preserved" in fda["note"]
    assert attempts == []
    assert tree(tools.pipeline.data_root) == before


# -- verification carries through to the FDA link --------------------------
def test_verify_reverifies_the_fda_link_from_the_preserved_archive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path, archive=archive_bytes())
    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    result = tools.verify_document(ELIQUIS_SET_ID, APPLICATION)

    linkage = result["drugs_fda_linkage"]
    assert result["result"] == "VERIFIED"
    assert result["raw_bytes_sha256"]["observed"] == "VERIFIED"
    assert result["section_anchors"]["observed"] == "VERIFIED"
    assert linkage["result"] == "VERIFIED"
    assert linkage["requested_application_number"] == APPLICATION
    assert linkage["matched_application_number"] == APPLICATION
    assert linkage["exact_match_status"] == "EXACT"
    assert linkage["archive_sha256_expected"] == linkage["archive_sha256_actual"]
    assert linkage["archive_path"]
    assert linkage["archive_sha256"]["observed"] == "VERIFIED"
    assert linkage["row_evidence"]["observed"] == "VERIFIED"
    assert linkage["link_status"]["observed"] == "VERIFIED"
    assert linkage["network_attempted"] is False
    for row in linkage["rows"]:
        assert row["zip_member"] and isinstance(row["row_number"], int) and row["row_sha256"]
    assert attempts == []
    assert tree(tools.pipeline.data_root) == before


def test_verify_does_not_connect_a_number_that_is_not_this_application(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path, archive=archive_bytes())
    attempts = forbid_network(monkeypatch)

    for requested in NOT_THIS_APPLICATION:
        linkage = tools.verify_document(ELIQUIS_SET_ID, requested)["drugs_fda_linkage"]

        assert linkage["requested_application_number"] == requested
        assert linkage["matched_application_number"] is None, requested
        assert linkage["result"] == "NOT_FOUND", requested
        assert linkage["rows"] == []
    assert attempts == []


def test_an_altered_archive_fails_the_fda_link_and_says_which_digest_differs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path, archive=archive_bytes())
    snapshot = tools.pipeline.drugsfda_store.preserved()[0]
    snapshot.archive_path.write_bytes(archive_bytes() + b"tampered")
    attempts = forbid_network(monkeypatch)

    result = tools.verify_document(ELIQUIS_SET_ID, APPLICATION)

    linkage = result["drugs_fda_linkage"]
    assert result["result"] == "FAILED"
    assert linkage["result"] == "FAILED"
    assert linkage["archive_sha256"]["observed"] == "FAILED"
    assert linkage["archive_sha256_expected"] != linkage["archive_sha256_actual"]
    # The label itself was not touched, and is not dragged down with the archive.
    assert result["raw_bytes_sha256"]["observed"] == "VERIFIED"
    assert attempts == []


def test_an_altered_label_fails_the_document_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path, archive=archive_bytes())
    raw = tools.pipeline.raw_store.resolve(ELIQUIS_SET_ID, ELIQUIS_VERSION)
    raw.label_path.write_bytes(raw.label_path.read_bytes() + b"<!-- tampered -->")
    attempts = forbid_network(monkeypatch)

    result = tools.verify_document(ELIQUIS_SET_ID, APPLICATION)

    # The store refuses to hand back bytes that disagree with their own immutable
    # manifest, so this is answered before any bundle is built -- with the two
    # digests that disagree, not with a bare refusal.
    assert result["result"] == "FAILED"
    assert result["failure_reasons"]
    failure = result["failures"][0]
    assert failure["expected_raw_sha256"] != failure["actual_raw_sha256"]
    assert attempts == []


def test_without_an_archive_only_the_fda_half_is_unresolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path)
    attempts = forbid_network(monkeypatch)

    result = tools.verify_document(ELIQUIS_SET_ID, APPLICATION)

    linkage = result["drugs_fda_linkage"]
    assert result["raw_bytes_sha256"]["observed"] == "VERIFIED"
    assert result["section_anchors"]["observed"] == "VERIFIED"
    assert result["result"] == "VERIFIED", "a missing archive is not a failed label"
    assert linkage["result"] == "NOT_PRESERVED"
    assert linkage["network_attempted"] is False
    assert attempts == []


# -- the whole surface ------------------------------------------------------
def test_every_tool_reads_and_only_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path, archive=archive_bytes())
    code = a_present_code(tools)
    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    tools.find_documents("apixaban")
    tools.get_section_index(ELIQUIS_SET_ID)
    tools.get_evidence_slice(ELIQUIS_SET_ID, [code], APPLICATION)
    tools.verify_document(ELIQUIS_SET_ID, APPLICATION)

    assert attempts == []
    assert tree(tools.pipeline.data_root) == before


def test_the_advertised_tools_declare_themselves_read_only() -> None:
    from odd.mcp.server import TOOL_DEFINITIONS

    for tool in TOOL_DEFINITIONS:
        assert tool.annotations is not None, tool.name
        assert tool.annotations.readOnlyHint is True, tool.name
        assert tool.annotations.destructiveHint is False, tool.name
        assert tool.annotations.openWorldHint is False, tool.name


def test_the_same_answers_come_back_over_the_protocol(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The offline contract is a property of the server, not of the Python call."""

    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    from odd.mcp.server import create_server

    tools = surface(tmp_path, archive=archive_bytes())
    code = a_present_code(tools)
    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        async with create_connected_server_and_client_session(
            create_server(tools=tools)
        ) as client:
            await client.initialize()

            async def call(name: str, **arguments: Any) -> dict[str, Any]:
                answer = await client.call_tool(name, arguments)
                return json.loads(answer.content[0].text)

            return (
                await call(
                    "odd_get_evidence_slice",
                    set_id=ELIQUIS_SET_ID,
                    section_codes=[code],
                    application_number=APPLICATION,
                ),
                await call(
                    "odd_verify_document",
                    set_id=ELIQUIS_SET_ID,
                    application_number=APPLICATION,
                ),
            )

    piece, verified = anyio.run(run)

    assert piece["drugs_fda"]["status"] == "EXACT"
    assert piece["drugs_fda"]["network_attempted"] is False
    assert verified["result"] == "VERIFIED"
    assert verified["drugs_fda_linkage"]["result"] == "VERIFIED"
    assert attempts == []
    assert tree(tools.pipeline.data_root) == before
