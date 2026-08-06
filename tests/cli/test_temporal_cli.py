from __future__ import annotations

import io
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from odd.cli.main import run_cli
from odd.service import create_service
from tests.odd002_support import SET_ID, temporal_service


@pytest.fixture(scope="module")
def cli_application(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("temporal-cli")
    application, old_id, new_id = temporal_service(root)
    result = application.diff_documents(old_id, new_id)
    return application, old_id, new_id, result.diff.diff_id


def _run(application, arguments: list[str]):
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = run_cli(arguments, service=application, stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def test_history_by_set_id_displays_lineage_versions_and_verification(
    cli_application: tuple,
) -> None:
    application, old_id, new_id, _diff_id = cli_application
    code, output, errors = _run(application, ["history", "--set-id", SET_ID])
    payload = json.loads(output)
    lineage = payload["lineages"][0]

    assert code == 0
    assert errors == ""
    assert lineage["source_document_id"] == SET_ID
    assert [item["source_version"] for item in lineage["versions"]] == ["29", "30"]
    assert [item["document_id"] for item in lineage["versions"]] == [old_id, new_id]
    assert all(item["verification_status"] == "verified" for item in lineage["versions"])
    assert lineage["ordering_edges"][0]["ordering"]["known_predecessor"] is True
    current = lineage["versions"][1]
    assert current["selection_publication_date"] == "2025-04-17"
    assert current["publication_date"] == "2025-05-05"
    assert current["publication_date_disagreement"] is True


def test_history_query_resolves_apixaban_lineage(cli_application: tuple) -> None:
    application, _old_id, _new_id, _diff_id = cli_application
    code, output, _errors = _run(application, ["history", "apixaban"])
    payload = json.loads(output)

    assert code == 0
    assert payload["count"] == 1
    assert payload["lineages"][0]["source_document_id"] == SET_ID


def test_diff_by_version_emits_machine_readable_artifact(cli_application: tuple) -> None:
    application, old_id, new_id, diff_id = cli_application
    code, output, errors = _run(
        application,
        [
            "diff",
            "--set-id",
            SET_ID,
            "--from-version",
            "29",
            "--to-version",
            "30",
            "--format",
            "json",
        ],
    )
    payload = json.loads(output)

    assert code == 0
    assert errors == ""
    assert payload["artifact"]["diff_id"] == diff_id
    assert payload["artifact"]["old_document_id"] == old_id
    assert payload["artifact"]["new_document_id"] == new_id
    assert payload["artifact"]["change_cause"] == "SOURCE_CHANGED"
    assert payload["canonical_sha256"]


def test_diff_by_document_labels_output_as_textual_not_clinical(
    cli_application: tuple,
) -> None:
    application, old_id, new_id, _diff_id = cli_application
    code, output, errors = _run(
        application,
        ["diff", "--old-document", old_id, "--new-document", new_id],
    )

    assert code == 0
    assert errors == ""
    assert "ODD textual source diff — not clinical interpretation" in output
    assert "Change cause: SOURCE_CHANGED" in output
    assert "Regulatory label change: yes" in output
    assert "SECTION_MODIFIED" in output


def test_verify_diff_success_returns_zero(cli_application: tuple) -> None:
    application, _old_id, _new_id, diff_id = cli_application
    code, output, errors = _run(application, ["verify-diff", "--diff", diff_id])
    payload = json.loads(output)

    assert code == 0
    assert errors == ""
    assert payload["ok"] is True
    assert all(item["ok"] for item in payload["checks"])


@pytest.mark.parametrize(
    "arguments",
    (
        ["history"],
        ["history", "apixaban", "--set-id", SET_ID],
        ["diff", "--old-document", "only-old"],
        ["diff", "--set-id", SET_ID, "--from-version", "29"],
    ),
)
def test_incomplete_or_mixed_cli_selectors_return_nonzero(
    cli_application: tuple, arguments: list[str]
) -> None:
    application, _old_id, _new_id, _diff_id = cli_application
    code, output, errors = _run(application, arguments)

    assert code != 0
    assert output == ""
    assert json.loads(errors)["error"]["category"] == "provenance_validation_failure"


def test_verify_diff_corruption_returns_nonzero(
    cli_application: tuple,
    tmp_path: Path,
) -> None:
    application, _old_id, _new_id, diff_id = cli_application
    copied_database = tmp_path / "tampered.sqlite3"
    shutil.copy2(application.repository.path, copied_database)
    tampered = create_service(data_root=tmp_path / "data", database_path=copied_database)
    with sqlite3.connect(copied_database) as connection:
        connection.execute(
            "UPDATE document_diffs SET canonical_sha256 = ? WHERE id = ?",
            ("0" * 64, diff_id),
        )
        connection.commit()

    code, output, errors = _run(tampered, ["verify-diff", "--diff", diff_id])
    payload = json.loads(output)

    assert code == 1
    assert errors == ""
    assert payload["ok"] is False
    assert next(
        item for item in payload["checks"] if item["name"] == "canonical_artifact_sha256"
    )["ok"] is False
