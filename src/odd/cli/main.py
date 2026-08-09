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
from odd.models import (
    BatchArtifactResult,
    BatchItem,
    BatchRun,
    BatchStatus,
    ChangeCause,
    DiffGenerationResult,
    DiffOperation,
)
from odd.models.enrichment import (
    EnrichmentArtifactResult,
    EnrichmentBudget,
    EnrichmentItem,
    EnrichmentRun,
)
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

    utilization = commands.add_parser(
        "utilization", help="inspect versioned external utilization inputs"
    )
    utilization_commands = utilization.add_subparsers(
        dest="utilization_command", required=True
    )
    utilization_commands.add_parser("list", help="list stored utilization inputs")
    utilization_show = utilization_commands.add_parser(
        "show", help="show one ranked utilization input"
    )
    utilization_show.add_argument("--list", required=True, dest="list_id")

    batch = commands.add_parser("batch", help="run ranked offline or ODD-004 live observations")
    batch_commands = batch.add_subparsers(dest="batch_command", required=True)
    batch_plan = batch_commands.add_parser("plan")
    plan_source = batch_plan.add_mutually_exclusive_group(required=True)
    plan_source.add_argument("--list", dest="list_id")
    plan_source.add_argument("--resume", dest="run_id")
    batch_plan.add_argument(
        "--new-observation",
        action="store_true",
        help="perform a new immutable live discovery; never implied by resume",
    )
    for name in ("fetch", "ingest", "verify", "run"):
        phase = batch_commands.add_parser(name)
        source = phase.add_mutually_exclusive_group(required=True)
        source.add_argument("--list", dest="list_id")
        source.add_argument("--run", dest="run_id")
    batch_status = batch_commands.add_parser("status")
    batch_status.add_argument("--run", required=True, dest="run_id")
    batch_report = batch_commands.add_parser("report")
    batch_report.add_argument("--run", required=True, dest="run_id")
    batch_report.add_argument("--format", choices=("text", "json"), default="text")
    batch_report.add_argument("--output", type=Path)

    candidates = commands.add_parser(
        "candidates", help="audit accepted and rejected DailyMed candidates"
    )
    candidates.add_argument("--ingredient", required=True)

    enrichment = commands.add_parser(
        "enrichment", help="plan and run bounded ODD-005 candidate enrichment"
    )
    enrichment_commands = enrichment.add_subparsers(
        dest="enrichment_command", required=True
    )
    enrichment_plan = enrichment_commands.add_parser("plan")
    enrichment_plan.add_argument("--parent-run", required=True)
    enrichment_plan.add_argument("--ranks", required=True, type=_parse_ranks)
    _add_enrichment_budget_arguments(enrichment_plan)

    enrichment_run = enrichment_commands.add_parser("run")
    run_source = enrichment_run.add_mutually_exclusive_group(required=True)
    run_source.add_argument("--parent-run")
    run_source.add_argument("--resume", dest="enrichment_run_id")
    enrichment_run.add_argument("--new-observation", action="store_true")
    enrichment_run.add_argument("--ranks", type=_parse_ranks)
    enrichment_run.add_argument("--parent-database-sha256")
    enrichment_run.add_argument("--max-tier", choices=(1, 2), type=int, required=True)
    _add_enrichment_budget_arguments(enrichment_run)

    enrichment_status = enrichment_commands.add_parser("status")
    enrichment_status.add_argument("--run", required=True, dest="enrichment_run_id")
    enrichment_evidence = enrichment_commands.add_parser("evidence")
    enrichment_evidence.add_argument("--run", required=True, dest="enrichment_run_id")
    enrichment_evidence.add_argument("--rank", type=int)
    enrichment_decisions = enrichment_commands.add_parser("decisions")
    enrichment_decisions.add_argument("--run", required=True, dest="enrichment_run_id")
    enrichment_decisions.add_argument("--rank", type=int)
    enrichment_report = enrichment_commands.add_parser("report")
    enrichment_report.add_argument("--run", required=True, dest="enrichment_run_id")
    enrichment_report.add_argument("--format", choices=("text", "json"), default="text")
    enrichment_report.add_argument("--output", type=Path)
    enrichment_verify = enrichment_commands.add_parser("verify")
    enrichment_verify.add_argument("--run", required=True, dest="enrichment_run_id")
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
        elif arguments.command == "utilization":
            if arguments.utilization_command == "list":
                values = application.utilization_lists()
                payload = {"count": len(values), "lists": values, "status": "ok"}
            else:
                payload = application.utilization_show(arguments.list_id)
        elif arguments.command == "batch":
            if arguments.batch_command == "plan":
                if arguments.run_id:
                    if arguments.new_observation:
                        raise ProvenanceValidationFailure(
                            "--new-observation cannot be combined with --resume"
                        )
                    run, items = application.batch_plan(run_id=arguments.run_id)
                else:
                    run, items = application.batch_plan(
                        arguments.list_id,
                        new_observation=arguments.new_observation,
                    )
                payload = _batch_payload(run, items)
                _write_json(output, payload)
                return 0
            if arguments.batch_command == "fetch":
                run, items = application.batch_fetch(
                    arguments.list_id, run_id=arguments.run_id
                )
                payload = _batch_payload(run, items)
            elif arguments.batch_command == "ingest":
                run, items = application.batch_ingest(
                    arguments.list_id, run_id=arguments.run_id
                )
                payload = _batch_payload(run, items)
            elif arguments.batch_command == "verify":
                run, items = application.batch_verify(
                    arguments.list_id, run_id=arguments.run_id
                )
                payload = _batch_payload(run, items)
            elif arguments.batch_command == "run":
                artifact = application.batch_run(
                    arguments.list_id, run_id=arguments.run_id
                )
                payload = _batch_artifact_payload(artifact)
                run = artifact.report.batch_run
                items = artifact.report.items
            elif arguments.batch_command == "status":
                run, items = application.batch_status(arguments.run_id)
                payload = _batch_payload(run, items)
                _write_json(output, payload)
                return 0
            elif arguments.batch_command == "report":
                artifact = application.batch_report(arguments.run_id)
                run = artifact.report.batch_run
                items = artifact.report.items
                if arguments.output is not None:
                    _write_batch_report_file(arguments.output, arguments.format, artifact)
                    _write_json(
                        output,
                        {
                            "canonical_report_sha256": artifact.canonical_sha256,
                            "output": str(arguments.output.resolve()),
                            "status": "ok",
                        },
                    )
                    return _batch_exit_code(run.status, items)
                if arguments.format == "text":
                    _write_batch_report_text(output, artifact)
                    return _batch_exit_code(run.status, items)
                payload = _batch_artifact_payload(artifact)
            else:  # pragma: no cover - argparse enforces the subcommand set
                raise AssertionError(f"unhandled batch command: {arguments.batch_command}")
            _write_json(output, payload)
            return _batch_exit_code(run.status, items)
        elif arguments.command == "candidates":
            values = application.candidates(arguments.ingredient)
            payload = {
                "candidate_count": len(values),
                "candidates": values,
                "ingredient": arguments.ingredient,
                "status": "ok",
            }
        elif arguments.command == "enrichment":
            if arguments.enrichment_command == "plan":
                payload = application.enrichment_plan(
                    arguments.parent_run,
                    ranks=arguments.ranks,
                    budget=_enrichment_budget(arguments),
                )
            elif arguments.enrichment_command == "run":
                if arguments.parent_run is not None:
                    if not arguments.new_observation:
                        raise ProvenanceValidationFailure(
                            "--parent-run requires explicit --new-observation"
                        )
                    if arguments.ranks is None or arguments.parent_database_sha256 is None:
                        raise ProvenanceValidationFailure(
                            "new enrichment observation requires --ranks and "
                            "--parent-database-sha256"
                        )
                    enrichment_run_value, _enrichment_items = (
                        application.enrichment_new_observation(
                        arguments.parent_run,
                        ranks=arguments.ranks,
                        parent_database_sha256=arguments.parent_database_sha256,
                        )
                    )
                    run_id = enrichment_run_value.enrichment_run_id
                else:
                    if arguments.new_observation:
                        raise ProvenanceValidationFailure(
                            "--new-observation cannot be combined with --resume"
                        )
                    if arguments.ranks is not None or arguments.parent_database_sha256 is not None:
                        raise ProvenanceValidationFailure(
                            "resume uses its stored parent/ranks and rejects parent-only options"
                        )
                    run_id = arguments.enrichment_run_id
                enrichment_artifact = application.enrichment_execute(
                    run_id,
                    budget=_enrichment_budget(arguments),
                    allow_tier2=arguments.max_tier == 2,
                )
                payload = _enrichment_artifact_payload(enrichment_artifact)
            elif arguments.enrichment_command == "status":
                enrichment_run_value, enrichment_items = application.enrichment_status(
                    arguments.enrichment_run_id
                )
                payload = _enrichment_payload(
                    enrichment_run_value, enrichment_items
                )
            elif arguments.enrichment_command == "evidence":
                evidence_values = application.enrichment_evidence(
                    arguments.enrichment_run_id, rank=arguments.rank
                )
                payload = {
                    "assertion_count": len(evidence_values),
                    "assertions": evidence_values,
                    "run_id": arguments.enrichment_run_id,
                    "status": "ok",
                }
            elif arguments.enrichment_command == "decisions":
                decision_values = application.enrichment_decisions(
                    arguments.enrichment_run_id, rank=arguments.rank
                )
                payload = {
                    "decision_revision_count": len(decision_values),
                    "decision_revisions": decision_values,
                    "run_id": arguments.enrichment_run_id,
                    "status": "ok",
                }
            elif arguments.enrichment_command == "report":
                enrichment_artifact = application.enrichment_report(
                    arguments.enrichment_run_id
                )
                if arguments.output is not None:
                    _write_enrichment_report_file(
                        arguments.output, arguments.format, enrichment_artifact
                    )
                    payload = {
                        "canonical_report_sha256": enrichment_artifact.canonical_sha256,
                        "output": str(arguments.output.resolve()),
                        "status": "ok",
                    }
                elif arguments.format == "text":
                    _write_enrichment_report_text(output, enrichment_artifact)
                    return 0
                else:
                    payload = _enrichment_artifact_payload(enrichment_artifact)
            elif arguments.enrichment_command == "verify":
                verification_values = application.enrichment_verify(
                    arguments.enrichment_run_id
                )
                payload = {
                    "checks": verification_values,
                    "ok": all(verification_values.values()),
                    "run_id": arguments.enrichment_run_id,
                    "status": (
                        "ok" if all(verification_values.values()) else "failed"
                    ),
                }
                _write_json(output, payload)
                return 0 if all(verification_values.values()) else 1
            else:  # pragma: no cover - argparse enforces the command set
                raise AssertionError(
                    f"unhandled enrichment command: {arguments.enrichment_command}"
                )
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


def _add_enrichment_budget_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-requests", type=int, required=True)
    parser.add_argument("--max-bytes", type=int, required=True)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--retry-limit", type=int, required=True)
    parser.add_argument("--rate-delay", type=float, required=True)
    parser.add_argument("--max-response-bytes", type=int, required=True)
    parser.add_argument("--max-detail-pages", type=int, required=True)
    parser.add_argument("--max-tier2-candidates", type=int, required=True)


def _enrichment_budget(arguments: argparse.Namespace) -> EnrichmentBudget:
    return EnrichmentBudget(
        max_requests=arguments.max_requests,
        max_downloaded_bytes=arguments.max_bytes,
        timeout_seconds=arguments.timeout,
        retry_limit=arguments.retry_limit,
        inter_request_delay_seconds=arguments.rate_delay,
        max_response_bytes=arguments.max_response_bytes,
        max_detail_pages=arguments.max_detail_pages,
        max_tier2_candidates=arguments.max_tier2_candidates,
    )


def _parse_ranks(value: str) -> tuple[int, ...]:
    try:
        ranks = tuple(sorted({int(item.strip()) for item in value.split(",")}))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("ranks must be comma-separated integers") from exc
    if not ranks or any(rank <= 0 for rank in ranks):
        raise argparse.ArgumentTypeError("ranks must be positive comma-separated integers")
    return ranks


def _enrichment_payload(
    run: EnrichmentRun, items: tuple[EnrichmentItem, ...]
) -> dict[str, Any]:
    return {
        "enrichment_run": run,
        "items": items,
        "status": "ok",
    }


def _enrichment_artifact_payload(
    artifact: EnrichmentArtifactResult,
) -> dict[str, Any]:
    return {
        "already_stored": artifact.already_stored,
        "canonical_report": json.loads(artifact.canonical_json),
        "canonical_report_sha256": artifact.canonical_sha256,
        "operational_report": artifact.report,
        "status": "ok",
    }


def _write_enrichment_report_text(
    stream: TextIO, artifact: EnrichmentArtifactResult
) -> None:
    report = artifact.report
    run = report.run
    stream.write("ODD-005 candidate enrichment report - not regulatory source data\n")
    stream.write(f"Run ID: {run.enrichment_run_id}\n")
    stream.write(f"Parent ODD-004 run: {run.parent_live_batch_run_id}\n")
    stream.write(f"Parent canonical SHA-256: {run.parent_canonical_sha256}\n")
    stream.write(f"Enrichment snapshot: {run.current_snapshot_id or 'none'}\n")
    stream.write(f"Status: {run.status.value}\n")
    stream.write(f"Canonical report SHA-256: {artifact.canonical_sha256}\n")
    stream.write(
        "Versions: "
        f"policy={run.selection_rule_version}, extractor={run.extractor_version}, "
        f"rules={run.extraction_rule_version}, connector={run.connector_version}, "
        f"parser={run.parser_version}, normalized_schema="
        f"{run.normalized_schema_version}, mapping={run.mapping_version}, "
        f"database_schema={run.database_schema_version}\n"
    )
    stream.write(
        "Summary: "
        f"items={len(report.items)}, complete={run.enrichment_complete_count}, "
        f"selected={run.selected_count}, manual_review={run.manual_review_count}, "
        f"incomplete={run.enrichment_incomplete_count}, source_drift={run.source_drift_count}, "
        f"ingested={run.ingested_count}, verified={run.verified_count}\n"
    )
    stream.write(
        "Transport: "
        f"requests={run.request_count}, bytes={run.downloaded_bytes}, "
        f"cache_hits={run.cache_hit_count}, retries={run.retry_count}, "
        f"http_429={run.http_429_count}, failures={run.failure_count}\n"
    )
    for item in report.items:
        stream.write(
            f"[{item.rank}] {item.ingredient_name}: candidates={item.candidate_total}, "
            f"tier0_excluded={item.candidates_excluded_tier0}, "
            f"tier1={item.tier1_complete}/{item.tier1_attempted}, "
            f"tier2={item.tier2_complete}/{item.tier2_attempted}, "
            f"eligible={item.candidates_proven_eligible}, "
            f"ineligible={item.candidates_proven_ineligible}, "
            f"unknown={item.candidates_unknown}, conflict={item.candidates_conflict}, "
            f"drift={item.source_drift_count}, completeness="
            f"{item.enrichment_completeness.value}, selection={item.selection_status.value}, "
            f"set_id={item.selected_set_id or 'none'}, version="
            f"{item.selected_source_version or 'none'}, ingest={item.ingestion_status.value}, "
            f"parser={item.parser_compatibility.value}, "
            f"verify={item.verification_status.value}\n"
        )
        stream.write(
            f"  parent_snapshot={item.parent_discovery_snapshot_id}, "
            f"requests={item.request_count}, bytes={item.downloaded_bytes}, "
            f"cache_hits={item.cache_hit_count}, retries={item.retry_count}, "
            f"http_429={item.http_429_count}, failures={item.failure_count}, "
            f"raw_xml_sha256={item.raw_xml_sha256 or 'none'}, "
            f"artifact_sha256={item.canonical_artifact_sha256 or 'none'}\n"
        )
        stream.write(f"  reason: {item.manual_review_reason}\n")


def _write_enrichment_report_file(
    path: Path,
    format_name: str,
    artifact: EnrichmentArtifactResult,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        path.write_bytes(artifact.canonical_json)
        return
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        _write_enrichment_report_text(stream, artifact)


def _batch_payload(run: BatchRun, items: tuple[BatchItem, ...]) -> dict[str, Any]:
    return {
        "batch_run": run,
        "items": items,
        "retry_eligible_ranks": [item.rank for item in items if item.retry_eligible],
        "status": "ok",
        "unresolved_ranks": [
            item.rank
            for item in items
            if item.manual_review_required or item.selection_status.value != "SELECTED"
        ],
    }


def _batch_artifact_payload(artifact: BatchArtifactResult) -> dict[str, Any]:
    return {
        "already_stored": artifact.already_stored,
        "artifact": json.loads(artifact.canonical_json),
        "canonical_report_sha256": artifact.canonical_sha256,
        "generation_metadata": {"generated_at": artifact.report.generated_at},
        "status": "ok",
    }


def _batch_exit_code(
    status: BatchStatus,
    items: tuple[BatchItem, ...] = (),
) -> int:
    if status is BatchStatus.FAILED:
        return 1
    if status in {
        BatchStatus.PARTIAL_FAILURE,
        BatchStatus.COMPLETED_WITH_UNRESOLVED_ITEMS,
    }:
        return 2
    if status is BatchStatus.RUNNING and any(
        item.error_category is not None
        or item.manual_review_required
        or item.quarantine_record_id is not None
        for item in items
    ):
        return 2
    return 0


def _write_batch_report_text(stream: TextIO, artifact: BatchArtifactResult) -> None:
    run = artifact.report.batch_run
    report_scope = "ODD-004 live" if run.observation_mode == "LIVE" else "ODD-003 derivative"
    stream.write(f"{report_scope} batch report - not regulatory source data\n")
    stream.write(f"Batch run ID: {run.batch_run_id}\n")
    stream.write(f"Utilization list: {run.utilization_list_id}\n")
    stream.write(f"Status: {run.status.value}\n")
    stream.write(f"Canonical report SHA-256: {artifact.canonical_sha256}\n")
    stream.write(
        "Versions: "
        f"policy={run.selection_rule_version} connector={run.connector_version} "
        f"parser={run.parser_version} normalized_schema={run.schema_version} "
        f"mapping={run.mapping_version} database_schema={run.database_schema_version}\n"
    )
    stream.write(
        "Counts: "
        f"requested={run.requested_count} selected={run.selected_count} "
        f"fetched={run.fetched_count} ingested={run.ingested_count} "
        f"verified={run.verified_count} quarantined={run.quarantined_count} "
        f"unresolved={run.unresolved_count} failed={run.failed_count}\n"
    )
    if run.observation_mode == "LIVE":
        stream.write(
            "Live counts: "
            f"discovery_complete={run.discovery_complete_count} "
            f"manual_review={run.manual_review_count} "
            f"no_candidate={run.no_candidate_count} "
            f"fetch_failure={run.fetch_failure_count} "
            f"parser_failure={run.parser_failure_count}\n"
        )
        stream.write(
            f"Snapshot manifest SHA-256: {run.snapshot_manifest_sha256 or '-'}\n"
        )
    stream.write(
        "rank ingredient selection version sections mapped unmapped "
        "compatibility verify\n"
    )
    for item in artifact.report.items:
        stream.write(
            f"{item.rank:>2} {item.ingredient_name} {item.selection_status.value} "
            f"{item.selected_source_version or '-'} "
            f"{item.source_section_count if item.source_section_count is not None else '-'} "
            f"{item.mapped_section_count if item.mapped_section_count is not None else '-'} "
            f"{item.unmapped_section_count if item.unmapped_section_count is not None else '-'} "
            f"{item.parser_compatibility_status.value} {item.verification_status.value}\n"
        )
        if run.observation_mode == "LIVE":
            metadata_total = (
                item.metadata_total_candidate_count
                if item.metadata_total_candidate_count is not None
                else "UNKNOWN"
            )
            stream.write(
                "   discovery: "
                f"query={item.query_text} snapshot={item.snapshot_id or '-'} "
                f"metadata_total={metadata_total} "
                f"retrieved={item.retrieved_candidate_count} "
                f"eligible={item.eligible_candidate_count} "
                f"completeness={item.discovery_completeness.value}\n"
            )
            stream.write(
                "   decision: "
                f"manual_review={str(item.manual_review_required).lower()} "
                f"set_id={item.selected_set_id or '-'} "
                f"spl_version={item.selected_source_version or '-'} "
                f"reason={item.selection_reason or '-'}\n"
            )
            stream.write(
                "   pipeline: "
                f"raw_sha256={item.raw_sha256 or '-'} "
                f"ingestion={item.ingestion_status.value} "
                f"parser={item.parser_compatibility_status.value} "
                f"document_verify={item.verification_status.value} "
                f"evidence_verify={item.evidence_verification_status.value} "
                f"error={item.error_category or '-'} "
                f"retry_eligible={str(item.retry_eligible).lower()}\n"
            )
        if item.diagnostic_message:
            stream.write(f"   diagnostic: {item.diagnostic_message}\n")


def _write_batch_report_file(
    path: Path,
    format_name: str,
    artifact: BatchArtifactResult,
) -> None:
    resolved = path.resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if format_name == "json":
        resolved.write_bytes(artifact.canonical_json)
        return
    with resolved.open("w", encoding="utf-8", newline="\n") as stream:
        _write_batch_report_text(stream, artifact)


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
