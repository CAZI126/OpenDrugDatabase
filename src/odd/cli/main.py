"""The ``odd`` command-line entry point."""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from odd.errors import (
    AmbiguousSourceSelection,
    ODDError,
    ProvenanceValidationFailure,
)
from odd.models import ChangeCause, DiffGenerationResult, DiffOperation
from odd.provenance.canonical import canonical_json_bytes
from odd.service import ODDService, create_service


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odd",
        description="Provenance-preserving DailyMed ingestion and temporal diff for ODD.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("ODD_DATA_DIR", "data")),
        help="data root containing raw, normalized, quarantine, and database directories",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(os.environ["ODD_DATABASE_PATH"])
        if "ODD_DATABASE_PATH" in os.environ
        else None,
        help="override the SQLite database path",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser("fetch", help="query DailyMed and preserve selected raw SPL bytes")
    fetch.add_argument("--drug", required=True)
    fetch.add_argument(
        "--source-version",
        help="explicit historical SPL version from the official DailyMed history",
    )

    ingest = commands.add_parser("ingest", help="parse and store a previously fetched raw SPL")
    ingest.add_argument("--set-id", required=True)
    ingest.add_argument("--source-version")

    search = commands.add_parser("search", help="search normalized local documents")
    search.add_argument("query")

    show = commands.add_parser("show", help="show one normalized document and source sections")
    show.add_argument("--document", required=True)
    show.add_argument("--section", help="filter by normalized section concept")

    verify = commands.add_parser("verify", help="verify provenance and reproducibility")
    verify.add_argument("--document", required=True)

    history = commands.add_parser("history", help="show stored lineage and source versions")
    history.add_argument("query", nargs="?", help="local drug, brand, or ingredient query")
    history.add_argument("--set-id", help="stable DailyMed source-document lineage")

    diff = commands.add_parser("diff", help="generate and persist a textual source diff")
    diff.add_argument("--set-id")
    diff.add_argument("--from-version")
    diff.add_argument("--to-version")
    diff.add_argument("--old-document")
    diff.add_argument("--new-document")
    diff.add_argument("--format", choices=("text", "json"), default="text")

    verify_diff = commands.add_parser("verify-diff", help="verify a stored diff artifact")
    verify_diff.add_argument("--diff", required=True, dest="diff_id")
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    service: ODDService | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    arguments = build_parser().parse_args(argv)
    application = service or create_service(
        data_root=arguments.data_dir,
        database_path=arguments.database,
    )
    try:
        payload: Any
        if arguments.command == "fetch":
            payload = application.fetch(arguments.drug, arguments.source_version)
        elif arguments.command == "ingest":
            payload = application.ingest(arguments.set_id, arguments.source_version)
        elif arguments.command == "search":
            documents = application.search(arguments.query)
            payload = {
                "count": len(documents),
                "documents": documents,
                "query": arguments.query,
                "status": "ok",
            }
        elif arguments.command == "show":
            result = application.show(arguments.document, arguments.section)
            payload = {
                **result,
                "section_filter": arguments.section,
                "status": "ok",
            }
        elif arguments.command == "verify":
            payload = application.verify(arguments.document)
            _write_json(output, payload)
            return 0 if payload.ok else 1
        elif arguments.command == "history":
            if bool(arguments.set_id) == bool(arguments.query):
                raise ProvenanceValidationFailure(
                    "history requires exactly one of --set-id or a search query"
                )
            payload = application.history(set_id=arguments.set_id, query=arguments.query)
        elif arguments.command == "diff":
            diff_result = _run_diff(application, arguments)
            if arguments.format == "text":
                _write_diff_text(output, diff_result)
                return 0
            payload = {
                "already_stored": diff_result.already_stored,
                "artifact": json.loads(diff_result.canonical_json),
                "canonical_sha256": diff_result.canonical_sha256,
                "generation_metadata": {
                    "generated_at": diff_result.diff.generated_at,
                    "new_raw_path": diff_result.diff.new_provenance.raw_path
                    if diff_result.diff.new_provenance
                    else None,
                    "new_retrieved_at": diff_result.diff.new_provenance.retrieved_at
                    if diff_result.diff.new_provenance
                    else None,
                    "old_raw_path": diff_result.diff.old_provenance.raw_path
                    if diff_result.diff.old_provenance
                    else None,
                    "old_retrieved_at": diff_result.diff.old_provenance.retrieved_at
                    if diff_result.diff.old_provenance
                    else None,
                },
                "status": "ok",
            }
        elif arguments.command == "verify-diff":
            payload = application.verify_diff(arguments.diff_id)
            _write_json(output, payload)
            return 0 if payload.ok else 1
        else:  # pragma: no cover - argparse enforces the command set
            raise AssertionError(f"unhandled command: {arguments.command}")
        _write_json(output, payload)
        return 0
    except ODDError as exc:
        _write_json(errors, {"error": exc.as_dict(), "status": "error"})
        return 2 if isinstance(exc, AmbiguousSourceSelection) else 1


def _write_json(stream: TextIO, value: Any) -> None:
    primitive = json.loads(canonical_json_bytes(value))
    json.dump(primitive, stream, ensure_ascii=False, indent=2, sort_keys=True)
    stream.write("\n")


def _run_diff(application: ODDService, arguments: argparse.Namespace) -> DiffGenerationResult:
    document_mode = bool(arguments.old_document or arguments.new_document)
    version_mode = bool(arguments.set_id or arguments.from_version or arguments.to_version)
    if document_mode and version_mode:
        raise ProvenanceValidationFailure(
            "diff accepts document IDs or set/version selectors, not both"
        )
    if document_mode:
        if not arguments.old_document or not arguments.new_document:
            raise ProvenanceValidationFailure(
                "diff document mode requires --old-document and --new-document"
            )
        return application.diff_documents(arguments.old_document, arguments.new_document)
    if not arguments.set_id or not arguments.from_version or not arguments.to_version:
        raise ProvenanceValidationFailure(
            "diff version mode requires --set-id, --from-version, and --to-version"
        )
    return application.diff_versions(
        arguments.set_id, arguments.from_version, arguments.to_version
    )


def _write_diff_text(stream: TextIO, result: DiffGenerationResult) -> None:
    diff = result.diff
    is_regulatory_change = ChangeCause.SOURCE_CHANGED in diff.change_components
    stream.write("ODD textual source diff — not clinical interpretation\n")
    stream.write(f"Diff ID: {diff.diff_id}\n")
    stream.write(f"Canonical SHA-256: {result.canonical_sha256}\n")
    stream.write(
        f"Versions: {diff.old_source_version or '-'} -> {diff.new_source_version or '-'}\n"
    )
    stream.write(f"Change cause: {diff.change_cause.value}\n")
    stream.write(
        "Change components: "
        + ", ".join(item.value for item in diff.change_components)
        + "\n"
    )
    stream.write(f"Regulatory label change: {'yes' if is_regulatory_change else 'no'}\n")
    stream.write(f"Ordering: {diff.ordering_status.value}\n")
    stream.write(
        "Sections: "
        f"+{diff.summary.sections_added} -{diff.summary.sections_removed} "
        f"modified={diff.summary.sections_modified} moved={diff.summary.sections_moved} "
        f"renamed={diff.summary.sections_renamed} "
        f"mapping-only/changed={diff.summary.section_mappings_changed}\n"
    )
    stream.write(
        f"Old raw SHA-256: {diff.old_raw_sha256 or '-'}\n"
        f"New raw SHA-256: {diff.new_raw_sha256 or '-'}\n"
    )
    for section in diff.section_diffs:
        if section.operations == (DiffOperation.NO_CHANGE,):
            continue
        operations = ", ".join(item.value for item in section.operations)
        heading = section.new_heading or section.old_heading or "<untitled>"
        stream.write(f"\n[{operations}] {heading}\n")
        stream.write(
            f"match={section.match_method.value}/{section.match_status.value}; "
            f"old={section.old_locator or '-'}; new={section.new_locator or '-'}\n"
        )
        if section.text_diff is not None and section.text_diff.unified_diff:
            stream.write(section.text_diff.unified_diff)
            stream.write("\n")


def main() -> None:
    # Regulatory text commonly contains characters outside legacy Windows code pages.
    # Configure only the process-owned console streams; injected test streams are untouched.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8")
    if isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
