"""Offline tests for the caller-side set-id conveyor.

The runner adds no retrieval and no selection of its own, so what is tested here
is what it does around the core call: every identity ends in exactly one class,
a failure does not cost the identities behind it, and a second run resumes from
the journal rather than conveying anything again.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from odd.connectors.dailymed.client import HTTPResponse
from odd.core.pipeline import CorePipeline
from tests.core.test_core_pipeline import ELIQUIS_SET_ID, _Transport, pipeline

_SPEC = importlib.util.spec_from_file_location(
    "run_set_id_batch",
    Path(__file__).resolve().parents[2] / "scripts" / "run_set_id_batch.py",
)
assert _SPEC and _SPEC.loader
runner = importlib.util.module_from_spec(_SPEC)
# A dataclass resolves its own module by name, so the module has to be findable
# before it is executed.
sys.modules[_SPEC.name] = runner
_SPEC.loader.exec_module(runner)

ABSENT_SET_ID = "00000000-0000-4000-8000-000000000000"


class _MissingTransport(_Transport):
    """A source that has the search page but not the document behind it."""

    def get(
        self, url: str, *, headers: Mapping[str, str], timeout: float, max_bytes: int
    ) -> HTTPResponse:
        if "/spls.json?" not in url and ABSENT_SET_ID in url:
            return HTTPResponse(status_code=404, url=url, body=b"", headers={})
        return super().get(url, headers=headers, timeout=timeout, max_bytes=max_bytes)


def drive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    set_ids: list[str],
    *,
    transport: _Transport | None = None,
    extra: list[str] | None = None,
) -> dict[str, Any]:
    """Run the script over these identities against a fixture source."""

    data_root = (tmp_path / "data").resolve()
    core = pipeline(tmp_path, transport=transport or _MissingTransport())
    monkeypatch.setattr(
        runner, "CorePipeline", lambda **kwargs: core if kwargs else CorePipeline(**kwargs)
    )
    listing = tmp_path / "set_ids.txt"
    listing.write_text("\n".join(set_ids) + "\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    runner.main(
        [
            "--set-id-file",
            str(listing),
            "--run-dir",
            str(run_dir),
            "--data-dir",
            str(data_root),
            *(extra or []),
        ]
    )
    return json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))


def journal(tmp_path: Path) -> list[dict[str, Any]]:
    lines = (tmp_path / "run" / "results.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_a_retrieved_identity_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = drive(tmp_path, monkeypatch, [ELIQUIS_SET_ID])

    assert summary["total_classified"] == 1
    assert summary["counts"][runner.VERIFIED] == 1
    row = journal(tmp_path)[0]
    assert row["set_id"] == ELIQUIS_SET_ID
    assert row["raw_sha256"] and row["source_url"] and row["section_count"] > 0
    assert row["was_preserved_before"] is False


def test_an_identity_the_source_does_not_have_is_classified_not_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = drive(tmp_path, monkeypatch, [ABSENT_SET_ID])

    assert summary["total_classified"] == 1
    assert summary["counts"][runner.VERIFIED] == 0
    assert sum(summary["counts"].values()) == 1
    row = journal(tmp_path)[0]
    assert row["classification"] in runner.CLASSES
    assert row["error"]


def test_one_failure_does_not_cost_the_identities_behind_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = drive(tmp_path, monkeypatch, [ABSENT_SET_ID, ELIQUIS_SET_ID])

    assert summary["total_classified"] == 2
    assert summary["counts"][runner.VERIFIED] == 1
    assert {row["set_id"] for row in journal(tmp_path)} == {ABSENT_SET_ID, ELIQUIS_SET_ID}


def test_every_supplied_identity_ends_in_exactly_one_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supplied = [ELIQUIS_SET_ID, ABSENT_SET_ID, ELIQUIS_SET_ID.upper()]

    summary = drive(tmp_path, monkeypatch, supplied)

    assert sum(summary["counts"].values()) == summary["total_classified"]
    recorded = {row["set_id"].casefold() for row in journal(tmp_path)}
    assert recorded == {value.casefold() for value in supplied}
    for row in journal(tmp_path):
        assert row["classification"] in runner.CLASSES


def test_a_second_run_resumes_from_the_journal_and_conveys_nothing_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drive(tmp_path, monkeypatch, [ELIQUIS_SET_ID])
    first = journal(tmp_path)

    summary = drive(tmp_path, monkeypatch, [ELIQUIS_SET_ID])

    assert summary["conveyed_this_run"] == 0
    assert journal(tmp_path) == first, "a resumed identity must not be conveyed twice"


def test_an_identity_already_preserved_is_recorded_as_already_stored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second data root visit re-verifies what is held; it does not retrieve it."""

    drive(tmp_path, monkeypatch, [ELIQUIS_SET_ID])
    (tmp_path / "run" / "results.jsonl").unlink()

    summary = drive(tmp_path, monkeypatch, [ELIQUIS_SET_ID])

    assert summary["counts"][runner.ALREADY_STORED_VERIFIED] == 1
    assert summary["counts"][runner.VERIFIED] == 0


def test_memberships_and_source_drift_are_recorded_against_the_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records = tmp_path / "records.jsonl"
    records.write_text(
        "\n".join(
            json.dumps({"set_id": ELIQUIS_SET_ID, "drug_name": name, "spl_version": "1"})
            for name in ("alpha", "beta")
        )
        + "\n",
        encoding="utf-8",
    )

    summary = drive(
        tmp_path, monkeypatch, [ELIQUIS_SET_ID], extra=["--records", str(records)]
    )

    row = journal(tmp_path)[0]
    assert row["memberships"] == ["alpha", "beta"], "one identity can be in two drugs"
    assert row["inventory_source_version"] == "1"
    assert row["observed_source_version"] != "1"
    assert row["source_drift"] is True
    assert summary["source_drift"] == [ELIQUIS_SET_ID]
    assert set(summary["per_drug"]) == {"alpha", "beta"}


def test_the_class_of_an_unmapped_reason_is_named_rather_than_absorbed() -> None:
    unmapped = {"status": "error", "error_code": "SOMETHING_NEW", "raw_sha256": "a" * 64}

    classification, mapped = runner.classify(unmapped, was_preserved=False)

    assert classification in runner.CLASSES
    assert mapped is False
