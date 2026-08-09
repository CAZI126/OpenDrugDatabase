"""ODD-004 explicit-observation and report CLI tests, fully offline."""

from __future__ import annotations

import io
import json

from odd.cli.main import run_cli
from odd.service import ODDService
from tests.odd004_support import live_service


def _invoke(application: ODDService, *arguments: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_cli(arguments, service=application, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_cli_distinguishes_new_observation_from_resume(tmp_path) -> None:
    application, transport = live_service(tmp_path)
    code, stdout, stderr = _invoke(
        application,
        "batch",
        "plan",
        "--list",
        "us-top10-2023",
        "--new-observation",
    )
    payload = json.loads(stdout)
    run_id = payload["batch_run"]["batch_run_id"]
    assert code == 0 and stderr == ""
    assert payload["batch_run"]["observation_mode"] == "LIVE"
    assert payload["batch_run"]["database_schema_version"] == "5"
    assert payload["batch_run"]["manual_review_count"] == 10
    assert transport.discovery_request_count == 10

    code, stdout, stderr = _invoke(
        application, "batch", "plan", "--resume", run_id
    )
    assert code == 0 and stderr == ""
    assert json.loads(stdout)["batch_run"]["batch_run_id"] == run_id
    assert transport.discovery_request_count == 10


def test_cli_writes_human_and_exact_canonical_reports(tmp_path) -> None:
    application, _transport = live_service(tmp_path)
    run, _items = application.batch_plan("us-top10-2023", new_observation=True)
    artifact = application.batch_run(run_id=run.batch_run_id)
    human_path = tmp_path / "reports" / "report.txt"
    json_path = tmp_path / "reports" / "report.json"

    code, stdout, stderr = _invoke(
        application,
        "batch",
        "report",
        "--run",
        run.batch_run_id,
        "--format",
        "text",
        "--output",
        str(human_path),
    )
    assert code == 2 and stderr == ""
    assert json.loads(stdout)["canonical_report_sha256"] == artifact.canonical_sha256
    human = human_path.read_text(encoding="utf-8")
    assert "database_schema=5" in human
    assert "discovery_complete=10" in human
    assert "manual_review=10" in human
    assert "metadata_total=" in human
    assert "retry_eligible=" in human

    code, stdout, stderr = _invoke(
        application,
        "batch",
        "report",
        "--run",
        run.batch_run_id,
        "--format",
        "json",
        "--output",
        str(json_path),
    )
    assert code == 2 and stderr == ""
    assert json_path.read_bytes() == artifact.canonical_json
    assert json.loads(json_path.read_bytes())["batch_run"]["batch_run_id"] is None


def test_manual_review_live_run_never_downloads_xml(tmp_path) -> None:
    application, transport = live_service(tmp_path)
    run, _items = application.batch_plan("us-top10-2023", new_observation=True)
    code, stdout, stderr = _invoke(
        application, "batch", "run", "--run", run.batch_run_id
    )
    payload = json.loads(stdout)
    assert code == 2 and stderr == ""
    assert payload["artifact"]["batch_run"]["status"] == (
        "COMPLETED_WITH_UNRESOLVED_ITEMS"
    )
    assert payload["artifact"]["batch_run"]["selected_count"] == 0
    assert transport.xml_request_count == 0
