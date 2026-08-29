"""The HTTP transport serves the same four read-only tools, and no more.

Only the transport is new. If HTTP could reach something stdio cannot, the
read-only guarantee would hold on one door and not the other, so what is tested
here is mostly that the two doors open onto the same room.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from odd.catalog import build_document_catalog
from odd.mcp._defaults import DEFAULT_HTTP_PORT, HTTP_PATH, LOOPBACK_HOST
from odd.mcp.server import TOOL_DEFINITIONS, create_http_app
from odd.mcp.tools import OddTools
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, pipeline
from tests.mcp.test_offline import forbid_network, tree

EXPECTED_TOOLS = [
    "odd_find_documents",
    "odd_get_section_index",
    "odd_get_evidence_slice",
    "odd_verify_document",
]


def surface(tmp_path: Path) -> OddTools:
    core = pipeline(tmp_path)
    core.acquire("Eliquis", set_id=ELIQUIS_SET_ID)
    build_document_catalog(core.data_root, parser=core.parser, clock=core.clock)
    return OddTools(core)


def test_the_http_app_mounts_the_mcp_endpoint(tmp_path: Path) -> None:
    app = create_http_app(tools=surface(tmp_path))

    mounted = [route.path for route in app.routes]

    assert mounted == [HTTP_PATH]


def test_the_defaults_bind_to_loopback() -> None:
    """Publishing beyond this machine is a separate decision, not a default."""

    assert LOOPBACK_HOST == "127.0.0.1"
    assert isinstance(DEFAULT_HTTP_PORT, int)


def test_http_exposes_the_same_four_tools_and_nothing_else(tmp_path: Path) -> None:
    """A tool absent from stdio must not appear because the transport changed."""

    assert [tool.name for tool in TOOL_DEFINITIONS] == EXPECTED_TOOLS
    for tool in TOOL_DEFINITIONS:
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False
        assert tool.annotations.openWorldHint is False


def test_no_retrieval_or_write_tool_is_advertised() -> None:
    """Nothing that fetches, updates or deletes is on the surface at all."""

    names = " ".join(tool.name for tool in TOOL_DEFINITIONS)
    for forbidden in ("fetch", "acquire", "download", "update", "delete", "write", "build"):
        assert forbidden not in names


def test_dns_rebinding_protection_is_on_and_scoped_to_loopback(tmp_path: Path) -> None:
    """A page on another origin must not be able to drive this through localhost."""

    from starlette.testclient import TestClient

    app = create_http_app(tools=surface(tmp_path), host=LOOPBACK_HOST, port=DEFAULT_HTTP_PORT)
    with TestClient(app) as client:
        refused = client.post(
            HTTP_PATH,
            headers={
                "Host": "attacker.example",
                "Origin": "http://attacker.example",
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert refused.status_code >= 400


def test_the_four_tools_answer_over_http_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real MCP client, a real ASGI round trip, no socket and no port."""

    import anyio
    import httpx
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    tools = surface(tmp_path)
    app = create_http_app(tools=tools)
    base = f"http://{LOOPBACK_HOST}:{DEFAULT_HTTP_PORT}{HTTP_PATH}"

    def through_the_app(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("transport", None)
        # The endpoint is mounted, so /mcp redirects to /mcp/. A real client
        # follows that; this one has to be told to.
        kwargs["follow_redirects"] = True
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), **kwargs)

    async def drive() -> dict[str, Any]:
        # The app's lifespan owns the session manager, so it has to be running.
        async with anyio.create_task_group():
            state: dict[str, Any] = {}
            async with app.router.lifespan_context(app):
                async with streamablehttp_client(
                    base, httpx_client_factory=through_the_app
                ) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        listed = await session.list_tools()
                        answer = await session.call_tool(
                            "odd_find_documents", {"query": "apixaban"}
                        )
                        state["tools"] = [t.name for t in listed.tools]
                        state["found"] = json.loads(answer.content[0].text)
            return state

    attempts = forbid_network(monkeypatch)
    before = tree(tools.pipeline.data_root)

    result = anyio.run(drive)

    assert result["tools"] == EXPECTED_TOOLS
    assert result["found"]["selection_performed"] is False
    assert result["found"]["candidate_count"] >= 1
    assert attempts == []
    assert tree(tools.pipeline.data_root) == before
