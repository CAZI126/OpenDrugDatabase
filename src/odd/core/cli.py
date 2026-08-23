"""The ``odd-core`` command line: the minimal path, and nothing attached to it.

This entry point deliberately imports only the core pipeline. It does not reach
the batch, enrichment, cohort, or research code paths, so the mainline stays
runnable and reviewable on its own.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from odd.core.batch import read_set_id_file, run_batch
from odd.core.pipeline import CorePipeline
from odd.errors import ODDError
from odd.provenance.canonical import canonical_json_bytes

# Neither success nor absence: the caller must narrow the identity, or the
# official listing was not observed completely enough to answer.
_UNRESOLVED_EXIT = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="odd",
        description=(
            "Deliver official primary-source drug labeling to an AI with provenance and "
            "evidence locators, and verify it back against the preserved raw source."
        ),
    )
    _add_shared_options(parser)
    commands = parser.add_subparsers(dest="command", required=True)

    fetch = commands.add_parser(
        "fetch", help="retrieve the official source and preserve its exact bytes"
    )
    fetch.add_argument("--drug", required=True, help="official lookup term, e.g. Eliquis")
    fetch.add_argument("--set-id", help="official DailyMed set id, when the term is ambiguous")
    fetch.add_argument("--source-version", help="official SPL version")

    extract = commands.add_parser(
        "extract", help="extract sections from preserved bytes and write the AI bundle"
    )
    extract.add_argument("--set-id", required=True)
    extract.add_argument("--source-version")
    extract.add_argument("--drug", help="record the term the caller asked for")
    _add_section_filters(extract)
    _add_drugsfda_option(extract)
    _add_selective_options(extract)

    verify = commands.add_parser(
        "verify", help="walk a written bundle back to the preserved raw source"
    )
    verify.add_argument("--set-id", required=True)
    verify.add_argument("--source-version")

    run = commands.add_parser("run", help="fetch, extract, and verify in one pass")
    run.add_argument("--drug", required=True)
    run.add_argument("--set-id")
    run.add_argument("--source-version")
    _add_section_filters(run)
    _add_drugsfda_option(run)
    _add_selective_options(run)

    batch = commands.add_parser(
        "batch",
        help="put a caller-supplied list of official identities through the same path",
    )
    batch.add_argument(
        "--set-id-file",
        required=True,
        type=Path,
        metavar="PATH",
        help="UTF-8 file with one official set id per line, in the order to process them",
    )
    batch.add_argument(
        "--drug",
        help=(
            "official lookup term to retrieve identities that are not preserved yet; "
            "without it, batch works only from already-preserved sources"
        ),
    )
    _add_drugsfda_option(batch)

    # Accept the shared options on either side of the subcommand.
    for subcommand in (fetch, extract, verify, run, batch):
        _add_shared_options(subcommand, subcommand_copy=True)
    return parser


def _add_shared_options(
    parser: argparse.ArgumentParser, *, subcommand_copy: bool = False
) -> None:
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=argparse.SUPPRESS
        if subcommand_copy
        else Path(os.environ.get("ODD_DATA_DIR", "data")),
        help="data root holding raw/ and evidence/ (default: data)",
    )
    parser.add_argument(
        "--print-evidence",
        action="store_true",
        default=argparse.SUPPRESS if subcommand_copy else False,
        help="print the whole evidence bundle instead of a summary",
    )


def _add_selective_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--index-only",
        action="store_true",
        help=(
            "return a text-free index of what the document contains, so a caller can "
            "name the sections it wants instead of receiving the whole document"
        ),
    )
    parser.add_argument(
        "--slice",
        dest="slice_only",
        action="store_true",
        help=(
            "return only the named --section-code sections, matched exactly, without "
            "widening a section to its subsections"
        ),
    )
    parser.add_argument(
        "--application-number",
        action="append",
        default=[],
        metavar="NUMBER",
        help="return only FDA rows for this application number (repeatable, exact match)",
    )


def _add_drugsfda_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-drugsfda",
        action="store_true",
        help=(
            "also preserve the official Drugs@FDA archive and cite what it states "
            "about this label's FDA application (off by default)"
        ),
    )


def _add_section_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--section-code",
        action="append",
        default=[],
        metavar="LOINC",
        help="return only sections with this official section code (repeatable)",
    )
    parser.add_argument(
        "--section-name",
        action="append",
        default=[],
        metavar="TEXT",
        help="return only sections whose official heading contains this text (repeatable)",
    )


def main(argv: Sequence[str] | None = None, stream: TextIO | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    pipeline = CorePipeline(data_root=arguments.data_dir)
    try:
        payload, code = _dispatch(pipeline, arguments)
    except ODDError as error:
        _emit({"error": error.as_dict(), "status": "error"}, stream)
        return 1
    _emit(payload if arguments.print_evidence else _summarize(payload), stream)
    return code


def _dispatch(
    pipeline: CorePipeline, arguments: argparse.Namespace
) -> tuple[dict[str, Any], int]:
    if arguments.command == "fetch":
        result = pipeline.acquire(
            arguments.drug,
            set_id=arguments.set_id,
            source_version=arguments.source_version,
        )
        return result.as_dict(), _UNRESOLVED_EXIT if result.raw is None else 0

    if arguments.command == "extract":
        evidence = pipeline.extract(
            arguments.set_id,
            arguments.source_version,
            requested_term=arguments.drug,
            section_codes=tuple(arguments.section_code),
            section_name_contains=tuple(arguments.section_name),
            include_drugsfda=arguments.include_drugsfda,
            index_only=arguments.index_only,
            slice_only=arguments.slice_only,
            application_numbers=tuple(arguments.application_number),
        )
        return (
            {
                "evidence": evidence.payload,
                "evidence_path": str(evidence.path),
                "evidence_status": evidence.status,
                "status": "extracted",
            },
            0,
        )

    if arguments.command == "batch":
        set_ids = read_set_id_file(arguments.set_id_file)
        batch_report = run_batch(
            pipeline,
            set_ids,
            drug=arguments.drug,
            include_drugsfda=arguments.include_drugsfda,
        )
        # A batch that ran is a batch that succeeded; per-item outcomes are inside.
        return batch_report, 0 if batch_report["error"] == 0 else 1

    if arguments.command == "verify":
        evidence = pipeline.load_evidence(arguments.set_id, arguments.source_version)
        report = pipeline.verify(evidence.payload)
        return (
            {
                "evidence_path": str(evidence.path),
                "status": "verified" if report.ok else "verification_failed",
                "verification": report.as_dict(),
            },
            0 if report.ok else 1,
        )

    run = pipeline.run(
        arguments.drug,
        set_id=arguments.set_id,
        source_version=arguments.source_version,
        section_codes=tuple(arguments.section_code),
        section_name_contains=tuple(arguments.section_name),
        include_drugsfda=arguments.include_drugsfda,
        index_only=arguments.index_only,
        slice_only=arguments.slice_only,
        application_numbers=tuple(arguments.application_number),
    )
    if run["status"] in {"ambiguous", "unknown"}:
        return run, _UNRESOLVED_EXIT
    return run, 0 if run["status"] in {"verified", "indexed"} else 1


def _emit(payload: dict[str, Any], stream: TextIO | None) -> None:
    """Write UTF-8 JSON without wrapping the stdout buffer.

    Building a second TextIOWrapper over ``sys.stdout.buffer`` lets whichever
    wrapper is finalized first close the shared buffer, which silently discarded
    anything the other had written -- ``--help`` printed nothing at all.
    """

    text = canonical_json_bytes(payload).decode("utf-8") + "\n"
    if stream is not None:
        stream.write(text)
        return
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
        return
    buffer.write(text.encode("utf-8"))
    buffer.flush()


def _summarize(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace section text with its length so a terminal stays readable."""

    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return payload
    sections = evidence.get("sections")
    if not isinstance(sections, list):
        return payload
    trimmed = dict(evidence)
    trimmed["sections"] = [
        {**section, "text": f"<{len(section.get('text', ''))} characters omitted>"}
        if isinstance(section, dict)
        else section
        for section in sections
    ]
    return {**payload, "evidence": trimmed}


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())
