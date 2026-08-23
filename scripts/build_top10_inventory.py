"""Turn frozen cohort definitions and preserved search snapshots into batch input.

This is caller-side tooling, deliberately outside ``odd.core``. The core never
learns what a cohort is: it is handed a list of official identities and puts
each one through the same path. Which identities belong to a study is the
caller's question, and it is answered here.

Nothing is selected. Every candidate the preserved snapshot recorded is kept,
including repackagers, combination products, and duplicates across ingredients.
A snapshot that cannot be shown to be complete is reported as incomplete rather
than quietly used.

Usage::

    python scripts/build_top10_inventory.py \
        --utilization-list src/odd/resources/us_top10_2023.json \
        --snapshot-root data/live/odd004-pilot-20260808/evidence/dailymed/discovery \
        --output-dir <writable directory outside the repository>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
ALLOWED_HOST = "dailymed.nlm.nih.gov"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, allow_nan=False, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def query_drug_name(url: str) -> str | None:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.hostname != ALLOWED_HOST or parsed.scheme != "https":
        return None
    values = parse_qs(parsed.query).get("drug_name")
    return values[0] if values else None


def audit_snapshot(directory: Path, expected_drug: str) -> dict[str, Any]:
    """Check a preserved snapshot end to end before any candidate is trusted."""

    problems: list[str] = []
    manifest = json.loads((directory / "manifest.json").read_bytes())
    declared_pages = int(manifest.get("total_pages") or 0)
    declared_total = int(manifest.get("metadata_total_elements") or 0)
    page_files = sorted(directory.glob("page-*.response"))

    seen_numbers = {
        int(re.fullmatch(r"page-(\d+)\.response", path.name).group(1))  # type: ignore[union-attr]
        for path in page_files
    }
    expected_numbers = set(range(1, declared_pages + 1))
    if seen_numbers != expected_numbers:
        problems.append(
            f"page numbering is not contiguous: missing {sorted(expected_numbers - seen_numbers)}, "
            f"unexpected {sorted(seen_numbers - expected_numbers)}"
        )

    by_number = {entry["page_number"]: entry for entry in manifest.get("pages", [])}
    records: list[dict[str, Any]] = []
    data_total = 0
    for path in page_files:
        number = int(re.fullmatch(r"page-(\d+)\.response", path.name).group(1))  # type: ignore[union-attr]
        body = path.read_bytes()
        entry = by_number.get(number)
        if entry is None:
            problems.append(f"page {number} has no manifest entry")
            continue
        if sha256_bytes(body) != entry.get("raw_sha256"):
            problems.append(f"page {number} bytes do not match the recorded SHA-256")
            continue
        for name, url in (("request_url", entry.get("request_url")),
                          ("response_url", entry.get("response_url"))):
            found = query_drug_name(str(url or ""))
            if found is None:
                problems.append(f"page {number} {name} lost its query or left the official host")
            elif found.casefold() != expected_drug.casefold():
                problems.append(
                    f"page {number} {name} asks for {found!r}, not {expected_drug!r}"
                )
        payload = json.loads(body)
        metadata = payload.get("metadata") or {}
        current = query_drug_name(str(metadata.get("current_url", "")))
        if current is None or current.casefold() != expected_drug.casefold():
            problems.append(f"page {number} current_url does not carry drug_name={expected_drug!r}")
        if int(metadata.get("current_page", -1)) != number:
            problems.append(
                f"page {number} reports current_page={metadata.get('current_page')!r}"
            )
        rows = payload.get("data") or []
        data_total += len(rows)
        size = int(metadata.get("elements_per_page") or 0)
        if size and len(rows) > size:
            problems.append(f"page {number} carries more rows than elements_per_page")
        for row in rows:
            records.append(
                {
                    "page_number": number,
                    "page_raw_sha256": entry["raw_sha256"],
                    "published_date": row.get("published_date"),
                    "request_url": entry.get("request_url"),
                    "response_url": entry.get("response_url"),
                    "set_id": str(row.get("setid", "")).strip(),
                    "spl_version": str(row.get("spl_version", "")).strip(),
                    "title": row.get("title"),
                }
            )
    if declared_total and data_total != declared_total:
        problems.append(
            f"pages carry {data_total} rows but metadata declares {declared_total}"
        )
    if manifest.get("completeness") != COMPLETE:
        problems.append(f"snapshot completeness is {manifest.get('completeness')!r}")
    return {
        "completeness": COMPLETE if not problems else INCOMPLETE,
        "declared_total_elements": declared_total,
        "declared_total_pages": declared_pages,
        "observed_pages": len(page_files),
        "observed_rows": data_total,
        "problems": problems,
        "records": records,
        "snapshot_id": manifest.get("snapshot_id"),
        "snapshot_path": directory.as_posix(),
    }


def locate_snapshots(root: Path) -> dict[str, Path]:
    """Map each snapshot directory to the drug_name its own bytes asked for."""

    found: dict[str, Path] = {}
    for directory in sorted(root.iterdir()):
        first = directory / "page-0001.response"
        if not first.is_file():
            continue
        payload = json.loads(first.read_bytes())
        name = query_drug_name(str((payload.get("metadata") or {}).get("current_url", "")))
        if name:
            found.setdefault(name.casefold(), directory)
    return found


def build(utilization: Path, snapshot_root: Path, output: Path) -> dict[str, Any]:
    cohort = json.loads(utilization.read_bytes())
    entries = sorted(cohort["entries"], key=lambda item: item["rank"])
    snapshots = locate_snapshots(snapshot_root)

    records: list[dict[str, Any]] = []
    per_drug: list[dict[str, Any]] = []
    for entry in entries:
        name = str(entry["ingredient_name"])
        directory = snapshots.get(name.casefold())
        if directory is None:
            per_drug.append(
                {
                    "completeness": INCOMPLETE,
                    "drug_name": name,
                    "problems": ["no preserved search snapshot for this ingredient"],
                    "rank": entry["rank"],
                    "snapshot_records": 0,
                    "unique_set_ids": 0,
                }
            )
            continue
        audit = audit_snapshot(directory, name)
        for record in audit["records"]:
            records.append({"drug_name": name, "rank": entry["rank"], **record})
        per_drug.append(
            {
                "completeness": audit["completeness"],
                "declared_total_elements": audit["declared_total_elements"],
                "declared_total_pages": audit["declared_total_pages"],
                "drug_name": name,
                "observed_pages": audit["observed_pages"],
                "observed_rows": audit["observed_rows"],
                "problems": audit["problems"],
                "rank": entry["rank"],
                "snapshot_id": audit["snapshot_id"],
                "snapshot_path": audit["snapshot_path"],
                "snapshot_records": len(audit["records"]),
                "unique_set_ids": len({item["set_id"] for item in audit["records"]}),
            }
        )

    # One identity may legitimately belong to several ingredients. The record
    # keeps every membership; the batch input carries it once.
    membership: dict[str, list[str]] = {}
    order: list[str] = []
    for record in records:
        key = record["set_id"]
        if key not in membership:
            membership[key] = []
            order.append(key)
        if record["drug_name"] not in membership[key]:
            membership[key].append(record["drug_name"])
    shared = {key: names for key, names in membership.items() if len(names) > 1}
    for detail in per_drug:
        detail["set_ids_shared_with_other_drugs"] = sum(
            1
            for key, names in shared.items()
            if detail["drug_name"] in names
        )

    output.mkdir(parents=True, exist_ok=True)
    records_path = output / "top10_records.jsonl"
    records_path.write_bytes(b"".join(canonical_json(item) + b"\n" for item in records))
    ids_path = output / "top10_set_ids.txt"
    ids_path.write_bytes("".join(f"{key}\n" for key in order).encode("utf-8"))

    summary = {
        "cohort": {
            "path": utilization.as_posix(),
            "sha256": sha256_bytes(utilization.read_bytes()),
            "utilization_list_id": cohort.get("utilization_list_id"),
            "entries": [
                {"rank": item["rank"], "ingredient_name": item["ingredient_name"]}
                for item in entries
            ],
        },
        "drugs": per_drug,
        "set_ids_in_more_than_one_drug": len(shared),
        "snapshot_records": len(records),
        "snapshot_root": snapshot_root.as_posix(),
        "unique_set_ids": len(order),
        "incomplete_drugs": [d["drug_name"] for d in per_drug if d["completeness"] != COMPLETE],
    }
    summary_path = output / "top10_inventory_summary.json"
    summary_path.write_bytes(canonical_json(summary) + b"\n")
    summary["artifacts"] = {
        "records": records_path.as_posix(),
        "set_ids": ids_path.as_posix(),
        "summary": summary_path.as_posix(),
    }
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build_top10_inventory")
    parser.add_argument("--utilization-list", required=True, type=Path)
    parser.add_argument("--snapshot-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    arguments = parser.parse_args(argv)
    summary = build(
        arguments.utilization_list, arguments.snapshot_root, arguments.output_dir
    )
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=1) + "\n")
    return 0 if not summary["incomplete_drugs"] else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
