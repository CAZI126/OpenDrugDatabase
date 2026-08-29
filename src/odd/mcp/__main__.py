"""Start the ODD MCP server.

Over stdio, which is the default::

    python -m odd.mcp --data-dir data

or over MCP's streamable HTTP transport, bound to loopback::

    python -m odd.mcp --http --data-dir data

Both serve exactly the same four read-only tools.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from odd.mcp._defaults import DEFAULT_HTTP_PORT, LOOPBACK_HOST


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m odd.mcp",
        description=(
            "Serve the ODD evidence pipeline to an MCP client over stdio, or over "
            "streamable HTTP with --http. Reads the preserved documents under "
            "--data-dir; retrieves nothing on its own."
        ),
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="serve over MCP streamable HTTP on the loopback interface instead of stdio",
    )
    parser.add_argument(
        "--host",
        default=LOOPBACK_HOST,
        help=f"interface to bind when --http is given (default: {LOOPBACK_HOST}). "
        "Binding beyond loopback publishes an unauthenticated server, and no "
        "authentication is implemented here.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_HTTP_PORT,
        help=f"port to bind when --http is given (default: {DEFAULT_HTTP_PORT})",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("ODD_DATA_DIR", "data")),
        help="data root holding raw/ and evidence/ (default: data, or $ODD_DATA_DIR)",
    )
    arguments = parser.parse_args(argv)

    try:
        from odd.mcp.server import run_http, run_stdio
    except ImportError:  # pragma: no cover - depends on what is installed
        sys.stderr.write(
            "the MCP SDK is not installed; install it with: pip install 'opendrugdatabase[mcp]'\n"
        )
        return 1

    try:
        if arguments.http:
            if arguments.host != LOOPBACK_HOST:
                # Say it plainly rather than let it happen quietly.
                sys.stderr.write(
                    f"warning: binding {arguments.host} exposes an unauthenticated "
                    "read-only server beyond this machine\n"
                )
            run_http(
                data_root=arguments.data_dir,
                host=arguments.host,
                port=arguments.port,
            )
        else:
            asyncio.run(run_stdio(data_root=arguments.data_dir))
    except KeyboardInterrupt:  # pragma: no cover - interactive interruption
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
