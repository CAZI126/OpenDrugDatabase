"""Put a caller-supplied list of set ids through ``odd.core``, one at a time.

This is a conveyor with a journal, and nothing else. Every identity goes through
:func:`odd.core.batch.run_batch` exactly as a single-document run would, and this
script only decides what to do around that call: where to write the outcome down,
which identities are already done, and which class of answer came back.

It adds no selection. The list is the caller's, in the caller's order; nothing is
ranked, excluded, deduplicated by resemblance, or substituted for something
easier to retrieve. An identity that fails is recorded with the reason and the
list moves on, because one document failing is not the other documents' problem.

The journal is written after every item, so an interrupted run resumes from what
is already recorded rather than starting over or, worse, retrieving again what is
already preserved.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - direct execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from odd.core.batch import run_batch
from odd.core.pipeline import CorePipeline

# Every identity ends in exactly one of these. There is no "skipped".
VERIFIED = "VERIFIED"
ALREADY_STORED_VERIFIED = "ALREADY_STORED_VERIFIED"
SOURCE_NOT_AVAILABLE = "SOURCE_NOT_AVAILABLE"
SOURCE_IDENTITY_MISMATCH = "SOURCE_IDENTITY_MISMATCH"
HTTP_FAILED = "HTTP_FAILED"
PARSE_FAILED = "PARSE_FAILED"
EXTRACT_FAILED = "EXTRACT_FAILED"
VERIFY_FAILED = "VERIFY_FAILED"

CLASSES = (
    VERIFIED,
    ALREADY_STORED_VERIFIED,
    SOURCE_NOT_AVAILABLE,
    SOURCE_IDENTITY_MISMATCH,
    HTTP_FAILED,
    PARSE_FAILED,
    EXTRACT_FAILED,
    VERIFY_FAILED,
)
# Only a transport failure is worth trying again; the rest are answers.
TRANSIENT = frozenset({HTTP_FAILED})

# What the core already says about a failure, mapped to what class it belongs in.
# Anything absent from this table is classified by the stage it stopped at, and
# named in the summary, so an unmapped reason is visible rather than absorbed.
BY_ERROR_CODE = {
    "NOT_IN_OFFICIAL_LISTING": SOURCE_NOT_AVAILABLE,
    "NOT_PRESERVED_LOCALLY": SOURCE_NOT_AVAILABLE,
    "SOURCE_NOT_FOUND": SOURCE_NOT_AVAILABLE,
    "NO_CANDIDATE": SOURCE_NOT_AVAILABLE,
    "INCOMPLETE_LISTING": SOURCE_NOT_AVAILABLE,
    "NETWORK_FAILURE": HTTP_FAILED,
    "CANDIDATE_LOOKUP_FAILED": HTTP_FAILED,
    "PROVENANCE_VALIDATION_FAILURE": SOURCE_IDENTITY_MISMATCH,
    "RAW_HASH_CONFLICT": SOURCE_IDENTITY_MISMATCH,
    "STORED_VERSION_DIFFERS": SOURCE_IDENTITY_MISMATCH,
    "AMBIGUOUS_STORED_VERSION": SOURCE_IDENTITY_MISMATCH,
    "AMBIGUOUS_OFFICIAL_CANDIDATES": SOURCE_IDENTITY_MISMATCH,
    "MALFORMED_XML": PARSE_FAILED,
    "PARSER_FAILURE": PARSE_FAILED,
    "MALFORMED_METADATA": PARSE_FAILED,
    "UNSUPPORTED_DOCUMENT_STRUCTURE": PARSE_FAILED,
    "EMPTY_SECTION_INDEX": EXTRACT_FAILED,
    "INCOMPLETE_SECTION_INDEX": EXTRACT_FAILED,
    "BLANK_SET_ID": SOURCE_IDENTITY_MISMATCH,
    "INDEX_VERIFICATION_FAILED": VERIFY_FAILED,
}


@dataclass
class Journal:
    """One line per finished identity, written before the next one starts."""

    path: Path
    lock: threading.Lock = field(default_factory=threading.Lock)

    def read(self) -> dict[str, dict[str, Any]]:
        if not self.path.is_file():
            return {}
        done: dict[str, dict[str, Any]] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                # A half-written final line from a killed run is not a result.
                continue
            if isinstance(record, dict) and record.get("set_id"):
                done[str(record["set_id"]).casefold()] = record
        return done

    def append(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
        with self.lock:
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(line)
                stream.flush()


def preserved_set_ids(data_root: Path) -> set[str]:
    """The identities already held here, read from the store's own layout."""

    container = data_root / "raw" / "dailymed"
    if not container.is_dir():
        return set()
    return {
        directory.name.casefold()
        for directory in container.iterdir()
        if directory.is_dir() and any(directory.glob("*/label.xml"))
    }


def classify(item: dict[str, Any], *, was_preserved: bool) -> tuple[str, bool]:
    """Which class this outcome belongs in, and whether the code was mapped."""

    if item.get("status") == "verified":
        return (ALREADY_STORED_VERIFIED if was_preserved else VERIFIED), True
    code = str(item.get("error_code") or "")
    mapped = BY_ERROR_CODE.get(code)
    if mapped is not None:
        return mapped, True
    # No mapping: fall back to the furthest stage this identity actually reached,
    # which the item states for itself.
    if item.get("index_status"):
        return VERIFY_FAILED, False
    if item.get("raw_sha256"):
        return EXTRACT_FAILED, False
    return HTTP_FAILED, False


def convey(
    set_id: str,
    *,
    data_root: Path,
    was_preserved: bool,
    memberships: Sequence[str],
    inventory_version: str | None,
) -> dict[str, Any]:
    """One identity through the single-document path, and what came back."""

    started = time.time()
    pipeline = CorePipeline(data_root=data_root)
    try:
        report = run_batch(pipeline, [set_id], fetch_missing_by_set_id=True)
        item = report["items"][0]
    except Exception as error:  # pragma: no cover - defensive, must not stop the list
        item = {
            "set_id": set_id,
            "status": "error",
            "error_code": type(error).__name__.upper(),
            "error": str(error),
        }
    classification, mapped = classify(item, was_preserved=was_preserved)
    observed_version = item.get("source_version")
    return {
        "set_id": set_id,
        "classification": classification,
        "error_code_mapped": mapped,
        "was_preserved_before": was_preserved,
        "memberships": list(memberships),
        "inventory_source_version": inventory_version,
        "observed_source_version": observed_version,
        "source_drift": bool(
            inventory_version
            and observed_version
            and str(inventory_version) != str(observed_version)
        ),
        "raw_sha256": item.get("raw_sha256"),
        "source_url": item.get("source_url"),
        "index_status": item.get("index_status"),
        "section_count": item.get("section_count"),
        "evidence_path": item.get("evidence_path"),
        "core_status": item.get("status"),
        "error_code": item.get("error_code"),
        "error": item.get("error"),
        "seconds": round(time.time() - started, 3),
    }


def read_set_ids(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def read_inventory(path: Path | None) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Memberships and the version the frozen snapshot recorded, per identity."""

    memberships: dict[str, list[str]] = {}
    versions: dict[str, str] = {}
    if path is None or not path.is_file():
        return memberships, versions
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        key = str(record["set_id"]).casefold()
        drug = str(record.get("drug_name", ""))
        if drug and drug not in memberships.setdefault(key, []):
            memberships[key].append(drug)
        versions.setdefault(key, str(record.get("spl_version", "")))
    return memberships, versions


def summarise(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    counts = Counter(row["classification"] for row in rows)
    per_drug: dict[str, Counter[str]] = {}
    for row in rows:
        for drug in row.get("memberships") or ["(no membership recorded)"]:
            per_drug.setdefault(drug, Counter())[row["classification"]] += 1
    return {
        "total_classified": len(rows),
        "counts": {name: counts.get(name, 0) for name in CLASSES},
        "per_drug": {drug: dict(counter) for drug, counter in sorted(per_drug.items())},
        "source_drift": sorted(
            {row["set_id"] for row in rows if row.get("source_drift")}
        ),
        "unmapped_error_codes": sorted(
            {
                str(row.get("error_code"))
                for row in rows
                if not row.get("error_code_mapped") and row.get("error_code")
            }
        ),
        "failed_set_ids": {
            name: sorted(row["set_id"] for row in rows if row["classification"] == name)
            for name in CLASSES
            if name not in {VERIFIED, ALREADY_STORED_VERIFIED}
            and any(row["classification"] == name for row in rows)
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="run_set_id_batch",
        description=(
            "Convey a caller-supplied list of official set ids through odd.core, "
            "recording every outcome and resuming from what is already recorded."
        ),
    )
    parser.add_argument("--set-id-file", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--records",
        type=Path,
        default=None,
        help="inventory JSONL carrying set_id, drug_name and spl_version, so "
        "memberships and source drift can be recorded against each identity",
    )
    parser.add_argument("--workers", type=int, default=1, help="1 to 4")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many")
    parser.add_argument(
        "--retry-transient",
        action="store_true",
        help="attempt identities a previous run recorded as HTTP_FAILED again",
    )
    parser.add_argument("--progress-every", type=int, default=100)
    arguments = parser.parse_args(argv)

    workers = max(1, min(4, arguments.workers))
    run_dir = arguments.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    journal = Journal(path=run_dir / "results.jsonl")
    data_root = arguments.data_dir.resolve()

    wanted = read_set_ids(arguments.set_id_file)
    memberships, versions = read_inventory(arguments.records)
    done = journal.read()
    if arguments.retry_transient:
        done = {
            key: record
            for key, record in done.items()
            if record.get("classification") not in TRANSIENT
        }
    preserved = preserved_set_ids(data_root)

    todo = [set_id for set_id in wanted if set_id.casefold() not in done]
    if arguments.limit is not None:
        todo = todo[: arguments.limit]

    print(
        f"identities: {len(wanted)} | already recorded: {len(done)} | "
        f"to convey now: {len(todo)} | workers: {workers} | data root: {data_root}",
        flush=True,
    )

    finished = 0
    started_at = time.time()

    def work(set_id: str) -> dict[str, Any]:
        key = set_id.casefold()
        return convey(
            set_id,
            data_root=data_root,
            was_preserved=key in preserved,
            memberships=memberships.get(key, []),
            inventory_version=versions.get(key) or None,
        )

    def record(result: dict[str, Any]) -> None:
        nonlocal finished
        journal.append(result)
        finished += 1
        if finished % arguments.progress_every == 0 or finished == len(todo):
            rate = finished / max(time.time() - started_at, 1e-9)
            remaining = (len(todo) - finished) / rate if rate else 0
            print(
                f"  {finished}/{len(todo)} conveyed | {rate:.2f}/s | "
                f"~{remaining / 60:.1f} min left",
                flush=True,
            )

    if workers == 1:
        for set_id in todo:
            record(work(set_id))
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for result in pool.map(work, todo):
                record(result)

    every = journal.read()
    summary = {
        "set_id_file": str(arguments.set_id_file),
        "data_root": str(data_root),
        "conveyed_this_run": len(todo),
        **summarise(every.values()),
    }
    (run_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    unclassified = [set_id for set_id in wanted if set_id.casefold() not in every]
    print(json.dumps(summary["counts"], ensure_ascii=False), flush=True)
    print(f"unprocessed: {len(unclassified)}", flush=True)
    return 0 if not unclassified else 1


if __name__ == "__main__":  # pragma: no cover - script entry point
    raise SystemExit(main())
