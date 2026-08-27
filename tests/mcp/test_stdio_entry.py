"""Smoke test for the documented entry point: ``python -m odd.mcp``.

This starts the real process and speaks newline-delimited JSON-RPC to it over
stdin and stdout, so a broken entry point cannot pass by being importable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_SECONDS = 60


def request(identifier: int, method: str, params: dict[str, Any]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params}
    )


def notification(method: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": method, "params": {}})


def speak(lines: list[str], data_dir: Path) -> list[dict[str, Any]]:
    """Run the server, feed it these lines, and decode the JSON-RPC it writes."""

    completed = subprocess.run(
        [sys.executable, "-m", "odd.mcp", "--data-dir", str(data_dir)],
        input="\n".join(lines) + "\n",
        capture_output=True,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    messages = []
    for line in completed.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:  # pragma: no cover - defensive
            continue
    if not messages:
        pytest.fail(
            f"server produced no JSON-RPC.\nexit={completed.returncode}\n"
            f"stdout={completed.stdout[:2000]}\nstderr={completed.stderr[:2000]}"
        )
    return messages


def test_the_documented_command_starts_and_completes_the_handshake(
    tmp_path: Path,
) -> None:
    messages = speak(
        [
            request(
                1,
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "odd-smoke", "version": "1"},
                },
            ),
            notification("notifications/initialized"),
            request(2, "tools/list", {}),
        ],
        tmp_path / "data",
    )

    by_id = {m.get("id"): m for m in messages if "id" in m}
    assert 1 in by_id, f"no initialize response: {messages}"
    initialize = by_id[1]["result"]
    assert initialize["serverInfo"]["name"] == "odd"
    assert "tools" in initialize["capabilities"]

    assert 2 in by_id, f"no tools/list response: {messages}"
    names = [tool["name"] for tool in by_id[2]["result"]["tools"]]
    assert names == [
        "odd_find_documents",
        "odd_get_section_index",
        "odd_get_evidence_slice",
        "odd_verify_document",
    ]


def test_the_running_server_answers_a_tool_call_over_stdio(tmp_path: Path) -> None:
    """An empty data root still answers honestly rather than failing to start."""

    messages = speak(
        [
            request(
                1,
                "initialize",
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "odd-smoke", "version": "1"},
                },
            ),
            notification("notifications/initialized"),
            request(
                2, "tools/call", {"name": "odd_find_documents", "arguments": {"query": "x"}}
            ),
        ],
        tmp_path / "data",
    )

    by_id = {m.get("id"): m for m in messages if "id" in m}
    assert 2 in by_id, f"no tools/call response: {messages}"
    payload = json.loads(by_id[2]["result"]["content"][0]["text"])
    assert payload["status"] == "ok"
    assert payload["candidate_count"] == 0
    assert payload["selection_performed"] is False


def test_the_entry_point_exposes_a_data_dir_option() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "odd.mcp", "--help"],
        capture_output=True,
        cwd=REPO_ROOT,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )

    assert completed.returncode == 0
    assert "--data-dir" in completed.stdout
