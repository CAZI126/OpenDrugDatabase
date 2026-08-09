"""ODD application service for ingestion, lineage, temporal diff, and verification."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from odd.batch import BatchCoordinator
from odd.batch.live_service import LiveBatchCoordinator
from odd.connectors.dailymed.client import DailyMedConnector
from odd.connectors.dailymed.selection import candidate_payload, select_apixaban_candidate
from odd.constants import HISTORICAL_SELECTION_RULE_VERSION
from odd.diffs.engine import DiffEngine
from odd.enrichment.service import EnrichmentCoordinator
from odd.errors import ODDError, RawHashConflict, UnsupportedDocumentStructure
from odd.models import (
    BatchArtifactResult,
    BatchItem,
    BatchRun,
    DailyMedCandidate,
    DiffGenerationResult,
    DiffVerificationResult,
    IngestionOutcome,
    RawDocument,
    SelectionDecision,
    UtilizationList,
    VerificationResult,
)
from odd.models.enrichment import (
    EnrichmentArtifactResult,
    EnrichmentBudget,
    EnrichmentDecisionRevision,
    EnrichmentItem,
    EnrichmentPlan,
    EnrichmentRun,
    EvidenceAssertion,
)
from odd.parsers.spl.parser import SPLParser
from odd.provenance.discovery_store import DiscoveryEvidenceStore
from odd.provenance.enrichment_store import EnrichmentEvidenceStore
from odd.provenance.hashing import sha256_bytes
from odd.provenance.raw_store import QuarantineStore, RawStore
from odd.storage.sqlite import SQLiteRepository
from odd.validation.verify import Verifier
from odd.validation.verify_diff import DiffVerifier
from odd.versioning import determine_version_order


class ODDService:
    """Coordinate the one-label pipeline through narrow injected interfaces."""

    def __init__(
        self,
        *,
        repository: SQLiteRepository,
        raw_store: RawStore,
        quarantine_store: QuarantineStore,
        connector: DailyMedConnector | None = None,
        parser: SPLParser | None = None,
        diff_engine: DiffEngine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.raw_store = raw_store
        self.quarantine_store = quarantine_store
        self.connector = connector
        self.parser = parser or SPLParser()
        self.diff_engine = diff_engine or DiffEngine()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.repository.initialize_schema()
        self.batch = BatchCoordinator(
            repository=self.repository,
            raw_store=self.raw_store,
            quarantine_store=self.quarantine_store,
            connector=self.connector or DailyMedConnector(clock=self.clock),
            ingest=self.ingest,
            verify=self.verify,
            clock=self.clock,
        )
        self.live_batch = LiveBatchCoordinator(
            repository=self.repository,
            raw_store=self.raw_store,
            discovery_store=DiscoveryEvidenceStore(self.raw_store.root.parent / "evidence"),
            quarantine_store=self.quarantine_store,
            connector=self.connector or DailyMedConnector(clock=self.clock),
            ingest=self.ingest,
            verify=self.verify,
            clock=self.clock,
        )
        self.enrichment = EnrichmentCoordinator(
            repository=self.repository,
            raw_store=self.raw_store,
            evidence_store=EnrichmentEvidenceStore(
                self.raw_store.root.parent / "evidence"
            ),
            connector=self.connector or DailyMedConnector(clock=self.clock),
            ingest=self.ingest,
            verify=self.verify,
            clock=self.clock,
        )

    def fetch(self, drug: str, source_version: str | None = None) -> dict[str, Any]:
        if drug.casefold().strip() != "apixaban":
            raise UnsupportedDocumentStructure("ODD-001 fetch supports only apixaban")
        connector = self.connector or DailyMedConnector(clock=self.clock)
        lookup = connector.lookup(drug)
        decision = select_apixaban_candidate(lookup)
        current_decision = decision
        history = None
        history_snapshot = None
        publication_date = decision.selected.published_date
        if source_version is None:
            download = connector.download(decision.selected)
        else:
            history = connector.history(decision.selected.set_id)
            entry = next(
                (item for item in history.entries if item.source_version == source_version),
                None,
            )
            if entry is None:
                from odd.errors import SourceNotFound

                raise SourceNotFound(
                    "requested source version is absent from DailyMed history",
                    details={
                        "set_id": decision.selected.set_id,
                        "source_version": source_version,
                        "known_versions": [item.source_version for item in history.entries],
                    },
                )
            historical_candidate = DailyMedCandidate(
                set_id=history.source_document_id,
                source_version=entry.source_version,
                title=history.title,
                published_date=entry.published_date_text,
                metadata={
                    "fixture_status": "genuine_dailymed_archive",
                    "published_date": entry.published_date_text,
                    "setid": history.source_document_id,
                    "spl_version": entry.source_version,
                    "title": history.title,
                },
            )
            decision = SelectionDecision(
                selected=historical_candidate,
                ordered_candidates=(
                    historical_candidate,
                    *(
                        item
                        for item in current_decision.ordered_candidates
                        if (item.set_id, item.source_version)
                        != (historical_candidate.set_id, historical_candidate.source_version)
                    ),
                ),
                rule_version=HISTORICAL_SELECTION_RULE_VERSION,
                rule_description=(
                    "Resolve the unique apixaban/Eliquis set_id with the ODD-001 rule; "
                    "then require the explicitly requested version in the official "
                    "DailyMed history response."
                ),
                reason=(
                    f"explicit source version {entry.source_version} was present in the "
                    f"official DailyMed history for set_id {history.source_document_id}."
                ),
                ambiguity_exposed=current_decision.ambiguity_exposed,
            )
            publication_date = entry.published_date_text
            download = connector.download_version(history, source_version)
        try:
            raw = self.raw_store.store(download, lookup, decision, history)
        except RawHashConflict as exc:
            self.quarantine_store.record(
                set_id=download.set_id,
                source_version=download.source_version,
                raw_sha256=sha256_bytes(download.body),
                stage="raw_storage",
                error=exc,
                recorded_at=self._now(),
                raw_bytes=download.body,
            )
            raise
        if history is not None:
            history_snapshot, _inserted = self.repository.store_history_snapshot(history)
        return {
            "ambiguity_exposed": decision.ambiguity_exposed,
            "candidate_count": len(decision.ordered_candidates),
            "candidates": [candidate_payload(item) for item in decision.ordered_candidates],
            "drug": "apixaban",
            "metadata_path": str(raw.metadata_path),
            "raw_path": str(raw.label_path),
            "raw_sha256": raw.identity.raw_sha256,
            "history_snapshot_id": history_snapshot,
            "publication_date": publication_date,
            "selected_set_id": decision.selected.set_id,
            "selection_reason": decision.reason,
            "selection_rule": decision.rule_description,
            "selection_rule_version": decision.rule_version,
            "source_version": decision.selected.source_version,
            "status": "already_stored" if raw.already_stored else "fetched",
        }

    def ingest(self, set_id: str, source_version: str | None = None) -> IngestionOutcome:
        raw = self.raw_store.resolve(set_id, source_version)
        run_id = self.repository.start_ingestion_run(raw.identity, self._now())
        try:
            xml_bytes = raw.label_path.read_bytes()
            normalized = self.parser.parse(xml_bytes, raw.identity)
            inserted = self.repository.store_document(
                normalized,
                raw,
                run_id=run_id,
                completed_at=self._now(),
            )
        except ODDError as exc:
            self._record_ingestion_failure(run_id, raw, exc)
            raise
        except OSError as exc:
            error = UnsupportedDocumentStructure(f"stored raw SPL could not be read: {exc}")
            self._record_ingestion_failure(run_id, raw, error)
            raise error from exc

        mapped_ids = {item.section_id for item in normalized.semantic_mappings}
        return IngestionOutcome(
            document_id=normalized.document.document_id,
            source_document_id=normalized.document.source_identity.source_document_id,
            source_version=normalized.document.source_identity.source_version,
            raw_sha256=normalized.document.source_identity.raw_sha256,
            source_section_count=len(normalized.sections),
            mapped_section_count=len(mapped_ids),
            unmapped_section_count=len(normalized.sections) - len(mapped_ids),
            status="ingested" if inserted else "already_ingested",
            ingestion_run_id=run_id,
        )

    def search(self, query: str) -> list[dict[str, Any]]:
        return self.repository.search(query.strip())

    def show(self, document_id: str, section: str | None = None) -> dict[str, Any]:
        document = self.repository.get_document(document_id)
        if document is None:
            from odd.errors import SourceNotFound

            raise SourceNotFound(
                "normalized document was not found", details={"document_id": document_id}
            )
        return {
            "document": document,
            "sections": self.repository.get_sections(document_id, section),
        }

    def verify(self, document_id: str) -> VerificationResult:
        return Verifier(self.repository, self.parser).verify(document_id)

    def history(
        self,
        *,
        set_id: str | None = None,
        query: str | None = None,
    ) -> dict[str, Any]:
        lineages = self.repository.find_lineages(set_id=set_id, query=query)
        payloads: list[dict[str, Any]] = []
        for lineage in lineages:
            lineage_id = str(lineage["id"])
            snapshot_id, known_history = self.repository.get_history_entries(lineage_id)
            documents = self.repository.get_lineage_documents(lineage_id)
            snapshots = {
                str(item["document_id"]): self.repository.get_stored_document(
                    str(item["document_id"])
                )
                for item in documents
            }
            edges = []
            for old_item, new_item in zip(documents, documents[1:], strict=False):
                old_snapshot = snapshots[str(old_item["document_id"])]
                new_snapshot = snapshots[str(new_item["document_id"])]
                ordering = determine_version_order(
                    old_snapshot,
                    new_snapshot,
                    history_entries=known_history,
                    history_snapshot_id=snapshot_id,
                )
                edges.append(
                    {
                        "from_document_id": old_snapshot.document_id,
                        "from_source_version": old_snapshot.provenance.source_version,
                        "to_document_id": new_snapshot.document_id,
                        "to_source_version": new_snapshot.provenance.source_version,
                        "ordering": ordering,
                    }
                )
            version_payloads = []
            for item in documents:
                document_id = str(item["document_id"])
                verification = self.verify(document_id)
                selection_date = item.get("selection_publication_date")
                history_date = item.get("publication_date")
                version_payloads.append(
                    {
                        **item,
                        "publication_date_disagreement": bool(
                            selection_date and history_date and selection_date != history_date
                        ),
                        "verification_status": "verified" if verification.ok else "failed",
                        "verification_ok": verification.ok,
                    }
                )
            payloads.append(
                {
                    "authority": lineage["authority"],
                    "history_snapshot_id": snapshot_id,
                    "jurisdiction": lineage["jurisdiction"],
                    "known_history_versions": [
                        {
                            "publication_date": item.published_date,
                            "publication_date_text": item.published_date_text,
                            "source_version": item.source_version,
                        }
                        for item in known_history
                    ],
                    "lineage_id": lineage_id,
                    "ordering_edges": edges,
                    "provider": lineage["provider"],
                    "source_document_id": lineage["source_document_id"],
                    "versions": version_payloads,
                }
            )
        return {
            "count": len(payloads),
            "lineages": payloads,
            "query": query,
            "set_id": set_id,
            "status": "ok",
        }

    def diff_documents(
        self,
        old_document_id: str,
        new_document_id: str,
    ) -> DiffGenerationResult:
        old = self.repository.get_stored_document(old_document_id)
        new = self.repository.get_stored_document(new_document_id)
        old_lineage = self.repository.get_lineage_id_for_document(old_document_id)
        new_lineage = self.repository.get_lineage_id_for_document(new_document_id)
        if old_lineage != new_lineage:
            from odd.errors import LineageMismatch

            raise LineageMismatch(
                "temporal diff documents do not share one stored lineage",
                details={"old_lineage_id": old_lineage, "new_lineage_id": new_lineage},
            )
        snapshot_id, history_entries = self.repository.get_history_entries(old_lineage)
        ordering = determine_version_order(
            old,
            new,
            history_entries=history_entries,
            history_snapshot_id=snapshot_id,
        )
        document_diff = self.diff_engine.generate(
            old,
            new,
            ordering=ordering,
            generated_at=self._now(),
        )
        canonical, canonical_sha256, inserted = self.repository.store_diff(document_diff)
        return DiffGenerationResult(
            diff=document_diff,
            canonical_json=canonical,
            canonical_sha256=canonical_sha256,
            already_stored=not inserted,
        )

    def diff_versions(
        self,
        set_id: str,
        old_source_version: str,
        new_source_version: str,
    ) -> DiffGenerationResult:
        old_document_id = self.repository.resolve_document_version(set_id, old_source_version)
        new_document_id = self.repository.resolve_document_version(set_id, new_source_version)
        return self.diff_documents(old_document_id, new_document_id)

    def verify_diff(self, diff_id: str) -> DiffVerificationResult:
        return DiffVerifier(self.repository, self.diff_engine, self.clock).verify(diff_id)

    def utilization_lists(self) -> list[dict[str, object]]:
        return self.batch.utilization_lists()

    def utilization_show(self, list_id: str) -> UtilizationList:
        return self.batch.utilization_show(list_id)

    def batch_plan(
        self,
        list_id: str | None = None,
        *,
        new_observation: bool = False,
        run_id: str | None = None,
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        if new_observation:
            if list_id is None or run_id is not None:
                raise ValueError("new live observation requires list_id and no run_id")
            return self.live_batch.new_observation(list_id)
        if run_id is not None:
            return self.live_batch.resume_plan(run_id)
        if list_id is None:
            raise ValueError("legacy batch plan requires list_id")
        return self.batch.plan(list_id)

    def batch_fetch(
        self, list_id: str | None = None, *, run_id: str | None = None
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        return self.live_batch.fetch(run_id) if run_id else self.batch.fetch(_required(list_id))

    def batch_ingest(
        self, list_id: str | None = None, *, run_id: str | None = None
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        return self.live_batch.ingest(run_id) if run_id else self.batch.ingest(_required(list_id))

    def batch_verify(
        self, list_id: str | None = None, *, run_id: str | None = None
    ) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        return self.live_batch.verify(run_id) if run_id else self.batch.verify(_required(list_id))

    def batch_run(
        self, list_id: str | None = None, *, run_id: str | None = None
    ) -> BatchArtifactResult:
        return self.live_batch.run(run_id) if run_id else self.batch.run(_required(list_id))

    def batch_status(self, run_id: str) -> tuple[BatchRun, tuple[BatchItem, ...]]:
        if self.repository.get_live_batch_run(run_id) is not None:
            return self.live_batch.status(run_id)
        return self.batch.status(run_id)

    def batch_report(self, run_id: str) -> BatchArtifactResult:
        if self.repository.get_live_batch_run(run_id) is not None:
            return self.live_batch.report(run_id)
        return self.batch.report(run_id)

    def candidates(self, ingredient: str) -> list[dict[str, object]]:
        return self.batch.candidates(ingredient)

    def enrichment_plan(
        self,
        parent_run_id: str,
        *,
        ranks: tuple[int, ...],
        budget: EnrichmentBudget,
    ) -> EnrichmentPlan:
        return self.enrichment.plan(parent_run_id, ranks=ranks, budget=budget)

    def enrichment_new_observation(
        self,
        parent_run_id: str,
        *,
        ranks: tuple[int, ...],
        parent_database_sha256: str,
    ) -> tuple[EnrichmentRun, tuple[EnrichmentItem, ...]]:
        return self.enrichment.new_observation(
            parent_run_id,
            ranks=ranks,
            parent_database_sha256=parent_database_sha256,
        )

    def enrichment_execute(
        self,
        run_id: str,
        *,
        budget: EnrichmentBudget,
        allow_tier2: bool,
    ) -> EnrichmentArtifactResult:
        return self.enrichment.execute(
            run_id, budget=budget, allow_tier2=allow_tier2
        )

    def enrichment_status(
        self, run_id: str
    ) -> tuple[EnrichmentRun, tuple[EnrichmentItem, ...]]:
        return self.enrichment.status(run_id)

    def enrichment_evidence(
        self, run_id: str, *, rank: int | None = None
    ) -> tuple[EvidenceAssertion, ...]:
        return self.enrichment.evidence(run_id, rank=rank)

    def enrichment_decisions(
        self, run_id: str, *, rank: int | None = None
    ) -> tuple[EnrichmentDecisionRevision, ...]:
        return self.enrichment.decisions(run_id, rank=rank)

    def enrichment_report(self, run_id: str) -> EnrichmentArtifactResult:
        return self.enrichment.report(run_id)

    def enrichment_verify(self, run_id: str) -> dict[str, bool]:
        return self.enrichment.verify_artifacts(run_id)

    def _record_ingestion_failure(
        self, run_id: int, raw: RawDocument, error: ODDError
    ) -> None:
        self.quarantine_store.record(
            set_id=raw.identity.source_document_id,
            source_version=raw.identity.source_version,
            raw_sha256=raw.identity.raw_sha256,
            stage="ingestion",
            error=error,
            recorded_at=self._now(),
            raw_path=raw.label_path,
        )
        self.repository.fail_ingestion_run(
            run_id,
            completed_at=self._now(),
            error_category=error.category.value,
            error_message=error.message,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def create_service(
    *,
    data_root: Path = Path("data"),
    database_path: Path | None = None,
    connector: DailyMedConnector | None = None,
    clock: Callable[[], datetime] | None = None,
) -> ODDService:
    resolved_data = data_root.resolve()
    resolved_database = (
        database_path.resolve()
        if database_path is not None
        else (resolved_data / "database" / "odd.sqlite3")
    )
    return ODDService(
        repository=SQLiteRepository(resolved_database),
        raw_store=RawStore(resolved_data / "raw"),
        quarantine_store=QuarantineStore(resolved_data / "quarantine"),
        connector=connector,
        clock=clock,
    )


def _required(value: str | None) -> str:
    if value is None:
        raise ValueError("batch list_id is required when no live run_id is provided")
    return value
