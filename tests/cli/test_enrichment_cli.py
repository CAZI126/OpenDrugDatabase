"""Offline CLI coverage for explicit bounded ODD-005 operations."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from odd.cli.main import build_parser, run_cli
from odd.provenance.hashing import sha256_file
from tests.odd005_support import odd005_service


def test_enrichment_plan_is_read_only_and_displays_hard_budget(tmp_path: Path) -> None:
    application, transport, parent_run_id = odd005_service(tmp_path)
    output = io.StringIO()
    code = run_cli(
        [
            "enrichment",
            "plan",
            "--parent-run",
            parent_run_id,
            "--ranks",
            "1",
            *_budget_arguments(),
        ],
        service=application,
        stdout=output,
    )
    payload = json.loads(output.getvalue())
    assert code == 0
    assert payload["planned_minimum_requests"] == 1
    assert payload["budget"]["max_requests"] == 3
    assert transport.packaging_request_count == 0


def test_enrichment_new_observation_run_status_and_report(tmp_path: Path) -> None:
    application, _transport, parent_run_id = odd005_service(tmp_path)
    output = io.StringIO()
    code = run_cli(
        [
            "enrichment",
            "run",
            "--parent-run",
            parent_run_id,
            "--new-observation",
            "--ranks",
            "1",
            "--parent-database-sha256",
            sha256_file(application.repository.path),
            "--max-tier",
            "1",
            *_budget_arguments(),
        ],
        service=application,
        stdout=output,
    )
    payload = json.loads(output.getvalue())
    run_id = payload["operational_report"]["run"]["enrichment_run_id"]
    assert code == 0
    assert payload["canonical_report_sha256"]

    status_output = io.StringIO()
    assert (
        run_cli(
            ["enrichment", "status", "--run", run_id],
            service=application,
            stdout=status_output,
        )
        == 0
    )
    assert json.loads(status_output.getvalue())["items"][0]["tier1_complete"] == 1

    report_output = io.StringIO()
    assert (
        run_cli(
            ["enrichment", "report", "--run", run_id, "--format", "text"],
            service=application,
            stdout=report_output,
        )
        == 0
    )
    report_text = report_output.getvalue()
    assert "ODD-005 candidate enrichment report" in report_text
    assert "Versions: policy=" in report_text
    assert "parent_snapshot=" in report_text
    assert "requests=1" in report_text

    json_path = tmp_path / "reports" / "enrichment.json"
    json_output = io.StringIO()
    assert (
        run_cli(
            [
                "enrichment",
                "report",
                "--run",
                run_id,
                "--format",
                "json",
                "--output",
                str(json_path),
            ],
            service=application,
            stdout=json_output,
        )
        == 0
    )
    artifact = application.enrichment_report(run_id)
    assert json_path.read_bytes() == artifact.canonical_json
    assert sha256_file(json_path) == artifact.canonical_sha256


def test_enrichment_live_run_requires_every_explicit_limit() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "enrichment",
                "run",
                "--resume",
                "run-id",
                "--max-tier",
                "1",
            ]
        )


def _budget_arguments() -> list[str]:
    return [
        "--max-requests",
        "3",
        "--max-bytes",
        "1000000",
        "--timeout",
        "5",
        "--retry-limit",
        "0",
        "--rate-delay",
        "0",
        "--max-response-bytes",
        "65536",
        "--max-detail-pages",
        "2",
        "--max-tier2-candidates",
        "0",
    ]
