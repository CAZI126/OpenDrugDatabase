"""A section that states no code can still be asked for, exactly.

Real labels carry sections with no ``<code>`` element, and one document can carry
several of them. A code cannot name one of those passages; the position the index
already reports can. These tests hold that path to the same exactness the code
path has: what was named comes back, and nothing else does.

Offline throughout: no network, and the data root is compared before and after.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from odd.catalog import build_document_catalog
from odd.core.direct import fetch_by_set_id
from odd.mcp.tools import OddTools, ToolError
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, ELIQUIS_XML, pipeline
from tests.mcp.test_offline import forbid_network, tree

_CODE_ELEMENT = re.compile(rb'\s*<code code="42229-5"[^>]*/>')


def codeless_xml() -> bytes:
    """The fixture with the first two subsection ``<code>`` elements removed.

    This is the shape the cohort run met in the wild: a whole, valid SPL whose
    subsections simply state no code of their own. Only the code elements go;
    every title, every passage and the document's identity stay as they were.
    """

    xml = ELIQUIS_XML.read_bytes()
    stripped = _CODE_ELEMENT.sub(b"", xml, count=2)
    assert stripped != xml, "the fixture must carry coded subsections to strip"
    return stripped


def surface(tmp_path: Path) -> OddTools:
    core = pipeline(tmp_path, xml_body=codeless_xml())
    fetch_by_set_id(core.connector, core.raw_store, ELIQUIS_SET_ID)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    return OddTools(core)


def codeless_entries(tools: OddTools) -> list[dict[str, Any]]:
    """The index entries for the sections that state no code, in document order."""

    index = tools.get_section_index(ELIQUIS_SET_ID)
    found = [e for e in index["sections"] if e["section_code"] == "UNKNOWN"]
    assert len(found) >= 2, f"expected two codeless sections, found {len(found)}"
    return found


# 1. the codeless section is visible in the index
def test_a_section_stating_no_code_still_appears_in_the_index(tmp_path: Path) -> None:
    first, second = codeless_entries(surface(tmp_path))[:2]

    for entry in (first, second):
        assert entry["section_code"] == "UNKNOWN", "no code stated is reported as unknown"
        assert entry["evidence_locator"], "but it always has a position"
    assert first["evidence_locator"] != second["evidence_locator"]


# 2. the position the index gave retrieves the text
def test_the_position_the_index_reported_retrieves_the_passage(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    first = codeless_entries(tools)[0]

    result = tools.get_evidence_slice(
        ELIQUIS_SET_ID, section_locators=[first["evidence_locator"]]
    )

    assert result["section_locators_not_found"] == []
    assert result["returned_section_locators"] == [first["evidence_locator"]]
    assert len(result["sections"]) == 1
    section = result["sections"][0]
    assert section["section_title"] == first["section_title"]
    assert section["evidence"]["xml_locator"] == first["evidence_locator"]
    assert section["evidence"]["section_sha256"]


# 3. the second codeless section is reachable on its own
def test_a_second_codeless_section_is_reachable_independently(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    second = codeless_entries(tools)[1]

    result = tools.get_evidence_slice(
        ELIQUIS_SET_ID, section_locators=[second["evidence_locator"]]
    )

    assert len(result["sections"]) == 1
    assert result["returned_section_locators"] == [second["evidence_locator"]]
    assert result["sections"][0]["section_title"] == second["section_title"]


# 4. naming one does not drag in the other, or any relative
def test_naming_one_position_returns_that_section_and_no_relative(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    first, second = codeless_entries(tools)[:2]

    result = tools.get_evidence_slice(
        ELIQUIS_SET_ID, section_locators=[first["evidence_locator"]]
    )

    assert result["returned_section_locators"] == [first["evidence_locator"]]
    assert second["evidence_locator"] not in result["returned_section_locators"]
    assert result["unexpected_section_codes"] == []
    assert result["subsections_added_implicitly"] is False


def test_a_parent_position_does_not_pull_in_its_children(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    index = tools.get_section_index(ELIQUIS_SET_ID)
    child = next(e for e in index["sections"] if e["depth"] > 0 and e["evidence_locator"])
    parent_locator = child["evidence_locator"].rsplit("/component[", 1)[0]

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, section_locators=[parent_locator])

    assert child["evidence_locator"] not in result["returned_section_locators"]


# 5. a position the document does not have
def test_a_position_the_document_lacks_is_reported_not_invented(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    absent = "/document[1]/component[1]/structuredBody[1]/component[999]/section[1]"

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, section_locators=[absent])

    assert result["section_locators_not_found"] == [absent]
    assert result["sections"] == []


def test_each_named_position_is_judged_on_its_own(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    real = codeless_entries(tools)[0]["evidence_locator"]
    absent = "/document[1]/component[1]/structuredBody[1]/component[999]/section[1]"

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, section_locators=[real, absent])

    assert result["section_locators_not_found"] == [absent]
    assert result["returned_section_locators"] == [real]


# 6. the existing code path is untouched
def test_selecting_by_section_code_behaves_exactly_as_before(tmp_path: Path) -> None:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    tools = OddTools(core)
    index = tools.get_section_index(ELIQUIS_SET_ID)
    code = next(
        e["section_code"] for e in index["sections"] if e["content_status"] == "present"
    )

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, [code])

    assert set(result["returned_section_codes"]) == {code}
    assert result["unexpected_section_codes"] == []
    assert result["section_codes_not_found"] == []
    assert result["requested_section_locators"] == []
    assert result["section_locators_not_found"] == []


def test_naming_neither_a_code_nor_a_position_is_a_structured_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(ToolError) as caught:
        surface(tmp_path).get_evidence_slice(ELIQUIS_SET_ID, [])

    assert caught.value.as_dict()["error"]["code"] == "NO_SECTION_CODES"


# 7. reachable over the MCP protocol
def test_a_position_can_be_named_over_the_protocol(tmp_path: Path) -> None:
    import anyio
    from mcp.shared.memory import create_connected_server_and_client_session

    from odd.mcp.server import create_server

    tools = surface(tmp_path)
    locator = codeless_entries(tools)[0]["evidence_locator"]

    async def run() -> dict[str, Any]:
        async with create_connected_server_and_client_session(
            create_server(tools=tools)
        ) as client:
            answer = await client.call_tool(
                "odd_get_evidence_slice",
                {"set_id": ELIQUIS_SET_ID, "section_locators": [locator]},
            )
            return json.loads(answer.content[0].text)

    result = anyio.run(run)

    assert result["status"] == "ok"
    assert result["returned_section_locators"] == [locator]


# 8. what came back still verifies against the preserved bytes
def test_a_document_sliced_by_position_still_verifies(tmp_path: Path) -> None:
    tools = surface(tmp_path)
    locator = codeless_entries(tools)[0]["evidence_locator"]
    tools.get_evidence_slice(ELIQUIS_SET_ID, section_locators=[locator])

    verified = tools.verify_document(ELIQUIS_SET_ID)

    assert verified["result"] == "VERIFIED"
    assert verified["raw_bytes_sha256"]["observed"] == "VERIFIED"
    assert verified["section_anchors"]["observed"] == "VERIFIED"


# 9 and 10. no network, no writes
def test_slicing_by_position_reaches_nothing_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tools = surface(tmp_path)
    locator = codeless_entries(tools)[0]["evidence_locator"]
    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    result = tools.get_evidence_slice(ELIQUIS_SET_ID, section_locators=[locator])

    assert result["sections"]
    assert attempts == []
    assert tree(tools.pipeline.data_root) == before
