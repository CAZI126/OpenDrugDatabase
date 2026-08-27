"""Smoke test for the documented entry point: ``python -m odd.mcp``.

This starts the real process and speaks newline-delimited JSON-RPC to it over
stdin and stdout, so a broken entry point cannot pass by being importable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
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


def speak(
    lines: list[str], data_dir: Path, awaiting: Sequence[int]
) -> dict[int, dict[str, Any]]:
    """Run the server, feed it these lines, and read until every id has answered.

    A client holds the connection open while it waits. Writing everything and
    closing stdin immediately is a race: end-of-input is a shutdown signal, and
    the server may take it before working through what was already written.
    """

    process = subprocess.Popen(
        [sys.executable, "-m", "odd.mcp", "--data-dir", str(data_dir)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    assert process.stdin and process.stdout and process.stderr
    # A server that never answers must fail the test rather than hang it.
    watchdog = threading.Timer(TIMEOUT_SECONDS, process.kill)
    watchdog.start()
    answers: dict[int, dict[str, Any]] = {}
    try:
        for line in lines:
            process.stdin.write(line + "\n")
        process.stdin.flush()
        while set(awaiting) - set(answers):
            written = process.stdout.readline()
            if not written:
                break
            try:
                message = json.loads(written.strip())
            except json.JSONDecodeError:  # pragma: no cover - defensive
                continue
            if isinstance(message, dict) and "id" in message:
                answers[int(message["id"])] = message
    finally:
        watchdog.cancel()
        process.stdin.close()
        try:
            process.wait(timeout=TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:  # pragma: no cover - defensive
            process.kill()
        errors = process.stderr.read()
    missing = sorted(set(awaiting) - set(answers))
    if missing:
        pytest.fail(
            f"server never answered {missing}.\nexit={process.returncode}\n"
            f"answered={sorted(answers)}\nstderr={errors[:2000]}"
        )
    return answers


def test_the_documented_command_starts_and_completes_the_handshake(
    tmp_path: Path,
) -> None:
    by_id = speak(
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
        awaiting=(1, 2),
    )

    initialize = by_id[1]["result"]
    assert initialize["serverInfo"]["name"] == "odd"
    assert "tools" in initialize["capabilities"]

    names = [tool["name"] for tool in by_id[2]["result"]["tools"]]
    assert names == [
        "odd_find_documents",
        "odd_get_section_index",
        "odd_get_evidence_slice",
        "odd_verify_document",
    ]


def test_the_running_server_answers_a_tool_call_over_stdio(tmp_path: Path) -> None:
    """An empty data root still answers honestly rather than failing to start."""

    by_id = speak(
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
        awaiting=(1, 2),
    )

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
