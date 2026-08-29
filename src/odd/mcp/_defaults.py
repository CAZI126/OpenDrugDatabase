"""Transport defaults, importable without the MCP SDK installed.

The entry point has to name these before it knows whether the SDK is present,
and the server has to use the same values, so they live in one place that
imports nothing.
"""

from __future__ import annotations

# Bound to loopback by design. Publishing this beyond the machine is a separate
# decision that needs authentication, and none is implemented here.
LOOPBACK_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 8765
HTTP_PATH = "/mcp"
