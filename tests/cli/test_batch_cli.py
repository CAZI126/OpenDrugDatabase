"""ODD-003 utilization, candidate-audit, and batch CLI behavior."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from odd.cli.main import run_cli
from odd.service import ODDService
from tests.odd003_support import odd003_service

LIST_ID = "us-top10-2023"


def _invoke(application: ODDService, *arguments: str) -> tuple[int, str, str]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_cli(arguments, service=application, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


@pytest.fixture(scope="module")
def completed(tmp_path_factory: pytest.TempPathFactory):
    application, _transport = odd003_service(
        tmp_path_factory.mktemp("odd003-cli-completed"),
        resolve_omeprazole=True,
    )
    artifact = application.batch_run(LIST_ID)
    return application, artifact.report.batch_run.batch_run_id


def test_utilization_list_cli(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    code, stdout, stderr = _invoke(application, "utilization", "list")
    payload = json.loads(stdout)
    assert code == 0 and stderr == ""
    assert payload["count"] == 1
    assert payload["lists"][0]["entry_count"] == 10


def test_utilization_show_cli(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    code, stdout, _stderr = _invoke(
        application,
        "utilization",
        "show",
        "--list",
        LIST_ID,
    )
    payload = json.loads(stdout)
    assert code == 0
    assert payload["entries"][6]["ingredient_name"] == "albuterol"
    assert payload["metric"] == "rank_only"


def test_batch_plan_is_nonfatal_when_one_item_is_unresolved(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    code, stdout, stderr = _invoke(application, "batch", "plan", "--list", LIST_ID)
    payload = json.loads(stdout)
    assert code == 0 and stderr == ""
    assert payload["batch_run"]["selected_count"] == 9
    assert payload["unresolved_ranks"] == [10]
    assert payload["items"][9]["selected_set_id"] is None
    assert payload["items"][0]["candidate_count"] == 2
    assert payload["items"][0]["query_text"] == "atorvastatin"
    assert "Selected set_id" in payload["items"][0]["selection_reason"]


def test_batch_run_all_verified_returns_zero(completed) -> None:
    application, _run_id = completed
    code, stdout, stderr = _invoke(application, "batch", "run", "--list", LIST_ID)
    payload = json.loads(stdout)
    assert code == 0 and stderr == ""
    assert payload["artifact"]["batch_run"]["status"] == "COMPLETED"
    assert payload["artifact"]["batch_run"]["verified_count"] == 10


@pytest.mark.parametrize("phase", ["fetch", "ingest", "verify"])
def test_batch_phase_commands_are_available_and_resumable(completed, phase: str) -> None:
    application, _run_id = completed
    code, stdout, stderr = _invoke(application, "batch", phase, "--list", LIST_ID)
    payload = json.loads(stdout)
    assert code == 0 and stderr == ""
    assert len(payload["items"]) == 10
    assert payload["batch_run"]["verified_count"] == 10


def test_batch_run_unresolved_returns_two(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    code, stdout, stderr = _invoke(application, "batch", "run", "--list", LIST_ID)
    payload = json.loads(stdout)
    assert code == 2 and stderr == ""
    assert payload["artifact"]["batch_run"]["unresolved_count"] == 1


def test_batch_status_displays_retry_and_item_state(completed) -> None:
    application, run_id = completed
    code, stdout, _stderr = _invoke(
        application,
        "batch",
        "status",
        "--run",
        run_id,
    )
    payload = json.loads(stdout)
    assert code == 0
    assert payload["batch_run"]["status"] == "COMPLETED"
    assert len(payload["items"]) == 10
    assert payload["retry_eligible_ranks"] == []


def test_batch_report_text_contains_counts_and_hash(completed) -> None:
    application, run_id = completed
    code, stdout, stderr = _invoke(
        application,
        "batch",
        "report",
        "--run",
        run_id,
    )
    assert code == 0 and stderr == ""
    assert "Canonical report SHA-256:" in stdout
    assert "requested=10 selected=10" in stdout
    assert "albuterol" in stdout


def test_batch_report_json_is_machine_readable(completed) -> None:
    application, run_id = completed
    code, stdout, _stderr = _invoke(
        application,
        "batch",
        "report",
        "--run",
        run_id,
        "--format",
        "json",
    )
    payload = json.loads(stdout)
    assert code == 0
    assert len(payload["canonical_report_sha256"]) == 64
    assert [item["rank"] for item in payload["artifact"]["items"]] == list(range(1, 11))


def test_candidates_cli_audits_albuterol_inhalation_and_otc_rejection(
    tmp_path: Path,
) -> None:
    application, _transport = odd003_service(tmp_path)
    application.batch_plan(LIST_ID)
    code, stdout, _stderr = _invoke(
        application,
        "candidates",
        "--ingredient",
        "albuterol",
    )
    payload = json.loads(stdout)
    assert code == 0
    assert payload["candidate_count"] == 2
    assert any(
        item["route"] == "RESPIRATORY (INHALATION)" for item in payload["candidates"]
    )
    assert any("OTC_PRODUCT" in item["classifications"] for item in payload["candidates"])


def test_partial_failure_returns_two(tmp_path: Path) -> None:
    application, _transport = odd003_service(
        tmp_path,
        resolve_omeprazole=True,
        fetch_failure_ingredient="albuterol",
    )
    code, stdout, _stderr = _invoke(application, "batch", "run", "--list", LIST_ID)
    payload = json.loads(stdout)
    assert code == 2
    assert payload["artifact"]["batch_run"]["status"] == "PARTIAL_FAILURE"


def test_unknown_utilization_list_is_fatal(tmp_path: Path) -> None:
    application, _transport = odd003_service(tmp_path)
    code, stdout, stderr = _invoke(
        application,
        "batch",
        "plan",
        "--list",
        "missing-list",
    )
    assert code == 1 and stdout == ""
    assert json.loads(stderr)["error"]["category"] == "utilization_input_invalid"
