"""MCP protocol wiring for the ODD tool surface.

Only the transport lives here. Every answer is produced by
:class:`odd.mcp.tools.OddTools`, which is the same core pipeline the CLI drives,
so the MCP server and the command line cannot drift into disagreeing about what
a document says.

Importing this module requires the ``mcp`` SDK. Nothing in ``odd.core`` imports
it, so the core stays installable with no dependencies at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server import Server

from odd.mcp.tools import OddTools, ToolError

SERVER_NAME = "odd"
SERVER_INSTRUCTIONS = (
    "ODD delivers official primary-source drug labeling with provenance and "
    "evidence locators. Work in this order: odd_find_documents to see which "
    "preserved documents a name matches, odd_get_section_index to see what a "
    "document contains without reading it, odd_get_evidence_slice to read only "
    "the sections you name, and odd_verify_document to re-check any of it "
    "against the preserved bytes. Every tool reads what is already preserved "
    "under the data root and retrieves nothing, so an FDA archive that was "
    "never preserved reads as NOT_PRESERVED rather than being fetched. ODD "
    "never chooses between matching documents and never states anything the "
    "sources do not; it transports primary sources and the positions the text "
    "was taken from, and it does not make medical judgements."
)

_SET_ID = {"type": "string", "description": "official DailyMed set id"}
_SOURCE_VERSION = {
    "type": "string",
    "description": "official SPL version; required only when several are preserved",
}
_APPLICATION_NUMBER = {
    "type": "string",
    "description": (
        "FDA application number, e.g. NDA123456. Matched by exact identity "
        "against an already-preserved Drugs@FDA archive; nothing is retrieved."
    ),
}
# Every tool reads preserved bytes and returns what they state. None of them
# retrieves anything, and none of them writes into the data root, so the hints
# below describe what the code does rather than asking for easier approval.
_READ_ONLY = types.ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

TOOL_DEFINITIONS: list[types.Tool] = [
    types.Tool(
        name="odd_find_documents",
        description=(
            "List every preserved document whose own title, brand name, generic "
            "name, or active ingredient matches the query. Returns all matches "
            "with their identities; ODD does not choose between them."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "drug or product name to match"}
            },
            "required": ["query"],
        },
        annotations=_READ_ONLY,
    ),
    types.Tool(
        name="odd_get_section_index",
        description=(
            "Return the index of every section in one preserved document: code, "
            "title, subsection relationship, evidence locator and digests. "
            "Carries no section text, so a caller can choose what to read."
        ),
        inputSchema={
            "type": "object",
            "properties": {"set_id": _SET_ID, "source_version": _SOURCE_VERSION},
            "required": ["set_id"],
        },
        annotations=_READ_ONLY,
    ),
    types.Tool(
        name="odd_get_evidence_slice",
        description=(
            "Return only the sections you name, matched exactly by section code or "
            "by evidence locator, with the locator and digests for each. A parent "
            "section is never widened to its subsections. Name a passage by "
            "section_codes, or by section_locators taken from the index when a "
            "section states no code of its own or several share one; at least one of "
            "the two is required. Supply application_number to also "
            "return what an already-preserved Drugs@FDA archive states about that "
            "exact application; with no archive preserved the FDA half comes back "
            "as NOT_PRESERVED, which is not the same as NOT_FOUND."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "set_id": _SET_ID,
                "section_codes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "official section codes, matched exactly",
                },
                "section_locators": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "section positions exactly as odd_get_section_index reported "
                        "them in evidence_locator, matched exactly. Use these when a "
                        "section states no code of its own, or when several sections "
                        "share one code and you want one of them."
                    ),
                },
                "application_number": _APPLICATION_NUMBER,
                "source_version": _SOURCE_VERSION,
            },
            "required": ["set_id"],
        },
        annotations=_READ_ONLY,
    ),
    types.Tool(
        name="odd_verify_document",
        description=(
            "Re-verify a bundle against the preserved raw source: raw SHA-256, "
            "every section anchor re-resolved, and source and version "
            "consistency. Name an application_number to carry the same "
            "re-verification through the FDA link -- the preserved archive is "
            "re-hashed, its cited rows re-read, and the exact-identity match "
            "recomputed. Returns VERIFIED or FAILED with the reasons."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "set_id": _SET_ID,
                "application_number": _APPLICATION_NUMBER,
                "source_version": _SOURCE_VERSION,
            },
            "required": ["set_id"],
        },
        annotations=_READ_ONLY,
    ),
]


def dispatch(tools: OddTools, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Route one tool call, turning every failure into structured data."""

    try:
        if name == "odd_find_documents":
            return tools.find_documents(str(arguments.get("query", "")))
        if name == "odd_get_section_index":
            return tools.get_section_index(
                str(arguments.get("set_id", "")), arguments.get("source_version")
            )
        if name == "odd_get_evidence_slice":
            codes = arguments.get("section_codes") or []
            if isinstance(codes, str):
                codes = [codes]
            locators = arguments.get("section_locators") or []
            if isinstance(locators, str):
                locators = [locators]
            return tools.get_evidence_slice(
                str(arguments.get("set_id", "")),
                [str(code) for code in codes],
                arguments.get("application_number"),
                arguments.get("source_version"),
                [str(locator) for locator in locators],
            )
        if name == "odd_verify_document":
            return tools.verify_document(
                str(arguments.get("set_id", "")),
                arguments.get("application_number"),
                arguments.get("source_version"),
            )
    except ToolError as error:
        return error.as_dict()
    return ToolError("UNKNOWN_TOOL", f"no such tool: {name}", tool=name).as_dict()


def create_server(*, data_root: Path | None = None, tools: OddTools | None = None) -> Server:
    """Build the MCP server over one ODD data root."""

    surface = tools if tools is not None else OddTools(data_root=data_root)
    server: Server = Server(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return TOOL_DEFINITIONS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
        payload = dispatch(surface, name, arguments or {})
        text = json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True)
        return [types.TextContent(type="text", text=text)]

    return server


async def run_stdio(*, data_root: Path | None = None) -> None:
    """Serve on stdio until the client disconnects."""

    from mcp.server.stdio import stdio_server

    server = create_server(data_root=data_root)
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
