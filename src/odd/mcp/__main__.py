"""Start the ODD MCP server on stdio: ``python -m odd.mcp``."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Sequence
from pathlib import Path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m odd.mcp",
        description=(
            "Serve the ODD evidence pipeline to an MCP client over stdio. Reads "
            "the preserved documents under --data-dir; retrieves nothing on its own."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("ODD_DATA_DIR", "data")),
        help="data root holding raw/ and evidence/ (default: data, or $ODD_DATA_DIR)",
    )
    arguments = parser.parse_args(argv)

    try:
        from odd.mcp.server import run_stdio
    except ImportError:  # pragma: no cover - depends on what is installed
        sys.stderr.write(
            "the MCP SDK is not installed; install it with: pip install 'opendrugdatabase[mcp]'\n"
        )
        return 1

    try:
        asyncio.run(run_stdio(data_root=arguments.data_dir))
    except KeyboardInterrupt:  # pragma: no cover - interactive interruption
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
