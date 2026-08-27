"""Expose the ODD core evidence pipeline to an AI client over MCP.

This package is a caller, not a second implementation. Every fact it returns
comes from ``odd.core``: the same retrieval, the same preserved bytes, the same
section index, the same exact-match slice, and the same re-verification against
the raw source. Nothing here parses a label, ranks a candidate, or decides which
document a question is about.

The tool layer in :mod:`odd.mcp.tools` holds no MCP dependency, so it can be
used and tested without the SDK installed. :mod:`odd.mcp.server` adds the
protocol wiring and is imported only when a server is actually started.
"""

from __future__ import annotations

from odd.mcp.tools import OddTools, ToolError

__all__ = ["OddTools", "ToolError"]
