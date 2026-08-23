# OpenDrugDatabase

OpenDrugDatabase (ODD) is an open-source version-control foundation for global regulatory drug
knowledge. Regulatory source documents are primary data. Normalized mappings and temporal diffs
are reproducible derivative data that retain traceability to exact source bytes.

## Start here: the core path

The mainline is one way in and one way back — official primary source, preserved
raw bytes and SHA-256, extracted sections, structured output with evidence
locators, then re-verification against those bytes:

```
odd-core run --drug Eliquis --set-id e9481622-7cc6-418a-acb6-c5450daae9b0
```

The core never selects a drug, ranks a product, adjudicates a claim, or guesses.
`odd-core fetch --drug Eliquis` returns every official candidate and stops.
See [docs/core_boundary.md](docs/core_boundary.md) for what is on the mainline
and what is held aside.

## Implemented scope: ODD-001 through ODD-005

ODD currently implements one production-oriented United States DailyMed SPL vertical slice for
apixaban/Eliquis.

ODD-001 provides:

- DailyMed metadata lookup, explicit candidate display, and deterministic Eliquis selection;
- immutable raw SPL storage by DailyMed `set_id` and source version;
- exact-byte SHA-256 provenance;
- deterministic typed parsing with section order, hierarchy, wording, XML locators, and tables;
- separate source, parser, normalized-schema, and mapping versions;
- transactional SQLite persistence and `fetch`, `ingest`, `search`, `show`, and `verify` commands.

ODD-002 adds:

- official DailyMed history lookup and historical ZIP retrieval;
- two genuine versions of the same Eliquis lineage:
  - version 29: SHA-256
    `ac5703e97b6c5f095ed319cdfd87d36b80a5cef0e0946251eae5587e4ceb8716`;
  - version 30: SHA-256
    `d6549bce376b88394da0a802a479a7bea699a48f6da3ae0be087f927e101e1aa`;
- explicit lineage snapshots, version edges, ordering evidence, and missing-version uncertainty;
- change-cause classification separating source, parser, schema, mapping, and ingestion metadata;
- deterministic hierarchy-aware section matching with recorded exact or heuristic methods;
- structured section additions, removals, modifications, moves, renames, mapping changes, and
  word-level text changes;
- immutable generated diff artifacts with their own engine version and SHA-256;
- `history`, `diff`, and `verify-diff` commands.

Internal UUIDs are deterministic ODD identifiers, not FDA or DailyMed regulatory identifiers.
Textual similarity and diffs are not clinical interpretation.

ODD-003 adds a deliberately narrow generalization test across this fixed rank-only utilization
input: atorvastatin, metformin, levothyroxine, lisinopril, amlodipine, metoprolol, albuterol,
losartan, gabapentin, and omeprazole. The list is a versioned external utilization input supplied
for ODD-003, not FDA or DailyMed data. Exact prescription counts were not independently archived,
so they are intentionally omitted.

For each ingredient ODD preserves the exact lookup response, classifies every candidate, records
accepted and rejected evidence, and either selects one validation label or exposes an unresolved
state. The `dailymed-top10-validation-selection/2.0.0` policy requires explicit human, current,
prescription, single-ingredient metadata; excludes combinations, repackaged, archived, non-human,
OTC, incomplete, and unsupported candidates; then prefers exact name, higher numeric source
version, and later publication date. Candidates still tied on authoritative fields require manual
review—response order and lexical `set_id` never manufacture a winner. One selected label is only
one deterministic validation label; it does not represent every formulation, route, manufacturer,
or product for that ingredient.

ODD-004 applies that policy to explicit observations of the official DailyMed v2 API. It retrieves
and hashes every advertised candidate page, validates totals and duplicate/conflicting results,
stores an immutable snapshot in files and additive SQLite schema v4 tables, and resumes without
mixing later search responses into the observation. Missing API metadata, incomplete pagination,
and equal supported candidates become `MANUAL_REVIEW_REQUIRED`; no command forces a winner.
Selected exact SPL bytes then pass through the existing raw, normalized, database, parser-
compatibility, and artifact verification boundaries. See the
[ODD-004 live runbook](docs/odd004-live-runbook.md) for the checked official contract, UNKNOWN
fields, operating limits, snapshot identity, and pilot procedure.

ODD-005 enriches the candidates in a complete ODD-004 snapshot with bounded, exact-byte official
DailyMed detail evidence. It first uses the smaller packaging metadata endpoint and considers SPL
XML only for an explicitly capped set of candidates that may still compete. Every extracted fact
is `PROVEN_TRUE`, `PROVEN_FALSE`, `UNKNOWN`, or `CONFLICT` and retains a JSON/XML locator,
source identity, raw hash, and versioned extractor rule. A source-version mismatch, incomplete
candidate coverage, conflicting evidence, missing non-repackager proof, or authoritative tie stops
selection. Previous decisions remain immutable revisions, and successful XML is reused for ingest
rather than downloaded again. See the
[ODD-005 enrichment runbook](docs/odd005-enrichment-runbook.md) for the official contract,
mandatory request/byte budgets, canary gates, source drift, resume, and report semantics.

## Installation

Python 3.12 or later is required.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On POSIX systems, activate with `source .venv/bin/activate`.

## CLI

Fetch and ingest the current and historical genuine source versions:

```console
odd fetch --drug apixaban --source-version 29
odd ingest --set-id e9481622-7cc6-418a-acb6-c5450daae9b0 --source-version 29
odd fetch --drug apixaban
odd ingest --set-id e9481622-7cc6-418a-acb6-c5450daae9b0 --source-version 30
```

Retrieve and verify normalized source data:

```console
odd search apixaban
odd show --document <DOCUMENT_ID>
odd show --document <DOCUMENT_ID> --section drug_interactions
odd verify --document <DOCUMENT_ID>
```

Inspect lineage and generate a temporal diff:

```console
odd history --set-id e9481622-7cc6-418a-acb6-c5450daae9b0
odd history apixaban

odd diff --set-id e9481622-7cc6-418a-acb6-c5450daae9b0 \
  --from-version 29 --to-version 30

odd diff --old-document <OLD_DOCUMENT_ID> --new-document <NEW_DOCUMENT_ID>
odd diff --old-document <OLD_DOCUMENT_ID> --new-document <NEW_DOCUMENT_ID> --format json
odd verify-diff --diff <DIFF_ID>
```

The default diff is clearly labeled as a textual source diff, not clinical interpretation.
`--format json` emits the structured artifact plus its canonical SHA and separate generation
metadata. Verification failures and ambiguous or incomplete selectors return non-zero status.

Place isolated-storage options before the command:

```console
odd --data-dir ./demo-data --database ./demo.sqlite3 history apixaban
```

Equivalent environment variables are `ODD_DATA_DIR` and `ODD_DATABASE_PATH`.

Inspect the ranked input, plan without downloading XML, and run or audit a batch:

```console
odd utilization list
odd utilization show --list us-top10-2023
odd batch plan --list us-top10-2023
odd batch fetch --list us-top10-2023
odd batch ingest --list us-top10-2023
odd batch verify --list us-top10-2023
odd batch run --list us-top10-2023
odd batch status --run <BATCH_RUN_ID>
odd batch report --run <BATCH_RUN_ID>
odd batch report --run <BATCH_RUN_ID> --format json
odd candidates --ingredient albuterol
```

Create a distinct live observation only with the explicit flag, then use its run ID for every
later phase. Keep live source and database artifacts under an ignored local directory:

```console
odd --data-dir ./data/live/odd004-pilot --database ./data/live/odd004-pilot/database/odd.sqlite3 batch plan --list us-top10-2023 --new-observation
odd --data-dir ./data/live/odd004-pilot --database ./data/live/odd004-pilot/database/odd.sqlite3 batch plan --resume <LIVE_RUN_ID>
odd --data-dir ./data/live/odd004-pilot --database ./data/live/odd004-pilot/database/odd.sqlite3 batch run --run <LIVE_RUN_ID>
odd --data-dir ./data/live/odd004-pilot --database ./data/live/odd004-pilot/database/odd.sqlite3 batch status --run <LIVE_RUN_ID>
odd --data-dir ./data/live/odd004-pilot --database ./data/live/odd004-pilot/database/odd.sqlite3 batch report --run <LIVE_RUN_ID> --format text --output ./data/live/odd004-pilot/reports/report.txt
odd --data-dir ./data/live/odd004-pilot --database ./data/live/odd004-pilot/database/odd.sqlite3 batch report --run <LIVE_RUN_ID> --format json --output ./data/live/odd004-pilot/reports/report.json
```

`--resume` never performs candidate discovery. Only another explicit `--new-observation` may
observe changed live search bytes. The canonical JSON report excludes timestamps, local paths, and
the operational run ID while retaining snapshot and decision evidence.

Plan and run a bounded ODD-005 rank-1 enrichment canary on a verified copy of the ODD-004 parent:

```console
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment plan --parent-run <ODD004_RUN_ID> --ranks 1 --max-requests 806 --max-bytes 220000000 --timeout 30 --retry-limit 1 --rate-delay 0.30 --max-response-bytes 262144 --max-detail-pages 2 --max-tier2-candidates 0
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment run --parent-run <ODD004_RUN_ID> --new-observation --ranks 1 --parent-database-sha256 <ODD004_DB_SHA256> --max-tier 1 --max-requests 806 --max-bytes 220000000 --timeout 30 --retry-limit 1 --rate-delay 0.30 --max-response-bytes 262144 --max-detail-pages 2 --max-tier2-candidates 0
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment run --resume <ENRICHMENT_RUN_ID> --max-tier 1 --max-requests 806 --max-bytes 220000000 --timeout 30 --retry-limit 1 --rate-delay 0.30 --max-response-bytes 262144 --max-detail-pages 2 --max-tier2-candidates 0
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment status --run <ENRICHMENT_RUN_ID>
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment evidence --run <ENRICHMENT_RUN_ID> --rank 1
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment decisions --run <ENRICHMENT_RUN_ID> --rank 1
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment report --run <ENRICHMENT_RUN_ID> --format json --output ./data/live/odd005-canary/reports/report.json
odd --data-dir ./data/live/odd005-canary --database ./data/live/odd005-canary/database/odd.sqlite3 enrichment verify --run <ENRICHMENT_RUN_ID>
```

Every enrichment plan and execution requires explicit request, byte, timeout, retry, pacing,
response-size, pagination, and Tier-2 caps. The shown values are an example envelope, not defaults
or a DailyMed quota. `--resume` reuses exact cached evidence; only `--new-observation` creates a new
enrichment run. Do not expand beyond the canary when Tier 1 leaves a large XML requirement.

Planning is non-fatal even when it exposes ambiguity. End-to-end batch commands return `0` when
all requested items verify, `2` for completed partial/unresolved results, and `1` for fatal command
or batch failure. Successful items are committed independently and reused on resume. Ambiguous
selection is not quarantined; malformed/failing selected source data can be quarantined without
deleting immutable raw bytes.

## Provenance and data layers

Current XML is stored as:

```text
data/raw/dailymed/{set_id}/{source_version}/
|-- label.xml
`-- metadata.json
```

A historical ZIP retrieval additionally stores the exact transport response:

```text
data/raw/dailymed/{set_id}/{source_version}/
|-- label.xml       # exact XML member bytes; never pretty-printed or rewritten
|-- source.zip      # exact DailyMed historical HTTP response
`-- metadata.json   # both XML and ZIP hashes plus exact history-response evidence
```

Files are created atomically and never replaced. Identical content is idempotent. Different
content at one source identity fails closed and can be quarantined without deleting either source.

The data boundaries are:

- raw XML/ZIP and retrieval manifests are immutable source evidence;
- normalized SQLite rows and canonical normalized JSON are deterministic derivatives;
- official history responses are independently hashed ordering evidence;
- temporal diffs are generated artifacts stored separately from regulatory source tables;
- utilization ranks, candidate evidence, batch state, parser-compatibility results, and canonical
  batch reports live in separate derivative/evidence tables;
- exact paginated candidate responses and their immutable manifests are stored under
  `data/evidence/dailymed/discovery/{snapshot_id}` (or beneath the selected live data root);
- exact candidate-detail responses, four-valued assertions, enrichment snapshots, immutable
  decision revisions, and canonical reports remain separate from the ODD-004 parent evidence;
- unknown and absent sections are not invented or silently discarded;
- every section diff retains old/new wording, headings, hashes, locators, concepts, and match method.

Normalized canonical JSON excludes retrieval time and URL. Canonical diff JSON fixes
`generated_at` and retrieval timestamps to `null` and uses a stable logical raw path; actual times
and absolute paths remain in source/generation metadata. Therefore different ingestion locations
or times do not masquerade as regulatory label changes.

`SOURCE_CHANGED` is the only single-cause classification treated as a regulatory source update.
`MULTIPLE_CAUSES` lists its individual components so callers can tell whether source bytes changed.

## Tests and executable evidence

Tests never require a live DailyMed service. ODD-002 commits two focused, exact XML fixtures and an
official history response with a reviewed provenance manifest and SHA-256 list. This is not a
DailyMed corpus mirror. The earlier reduced ODD-001 parser fixture remains clearly identified.

```powershell
python -m pytest
python -m ruff check .
python -m mypy src/odd
python scripts\verify_fixture_integrity.py
python scripts\verify_temporal_diff.py
python scripts\verify_odd003_utilization.py
python scripts\verify_odd004_live_contract.py
python scripts\verify_odd005_enrichment_contract.py
python -m pytest tests\parsers\test_spl_parser.py::test_repeated_parsing_is_byte_deterministic
python -m pytest tests\diffs\test_genuine_temporal_diff.py::test_canonical_diff_is_timestamp_independent_and_idempotent
python -m pytest tests\connectors\test_dailymed_batch_selection.py::test_response_order_does_not_change_winner_or_evidence_order
python -m pytest tests\batch\test_batch_execution.py::test_batch_report_items_and_diagnostics_are_deterministic
python -m pytest tests\storage\test_batch_storage.py::test_v2_to_v3_migration_preserves_source_diff_and_verification
python -m pytest tests\storage\test_batch_storage.py::test_fresh_and_v3_to_v4_migrated_schema_contracts_match
python -m pytest tests\connectors\test_dailymed_live_discovery.py::test_discover_retrieves_and_hashes_every_advertised_page
python -m pytest tests\batch\test_live_batch_execution.py::test_resume_never_performs_additional_candidate_discovery
python -m pytest tests\batch\test_live_batch_execution.py::test_canonical_live_report_ignores_run_id_and_detects_tampering
python -m pytest tests\enrichment\test_evidence_extraction.py
python -m pytest tests\enrichment\test_enrichment_execution.py
```

CI runs these checks independently on Python 3.12 and never contacts DailyMed.

## Known limitations

- The parser supports the reviewed common HL7 v3 SPL structures. Multiple `structuredBody`
  elements, DTD/entity declarations, unsupported date forms, archives without exactly one SPL XML
  member, and unreviewed variants fail explicitly.
- Content-assisted matching is deterministic with a fixed threshold and is labeled heuristic. It
  does not establish clinical or semantic equivalence.
- Text-preservation tests cover selected numbers, units, comparison operators, negation,
  qualifiers, tables, and hierarchy. They are not complete clinical validation.
- Source publication metadata can disagree across DailyMed endpoints. ODD records both values and
  exposes the discrepancy rather than silently selecting one.
- Live fetch depends on DailyMed availability and its response contract; CI is fully offline. A
  live report is an observation at retrieval time, not a permanent currentness guarantee.
- DailyMed candidate metadata can be incomplete. ODD does not infer chemical equivalence for
  salts, esters, complexes, formulations, or combination products and may require manual review.
- The documented DailyMed packaging detail response does not prove the absence of repackaging.
  ODD-005 therefore keeps non-repackager status `UNKNOWN` unless a future official, versioned
  evidence rule can prove it; it does not treat a missing code as favorable evidence.
- `FULLY_PARSED` means no empty or unmapped sections were observed by the current parser; it is not
  clinical validation. Other explicit states report unmapped sections, unsupported structures,
  partial parsing, parser failure, or a document that was not ingested.
- The top-ten rank input may lag current prescribing patterns, and no exact utilization counts are
  asserted. Mocked candidate fixtures prove deterministic behavior, not current live availability.
- Broader redistribution and licensing questions for DailyMed collections are unresolved. Only
  two focused source-version fixtures are retained here for reproducible verification.
- EMA, PMDA, cross-regulatory comparison, REST/API changes, SDK, Web UI, AI/LLM/MCP changes,
  alerting, scheduling, corpus synchronization, and community features are intentionally deferred.

ODD is not yet a complete FDA, EMA, or PMDA database. Normalized ODD data and generated diffs are
not substitutes for the official regulatory source and are not medical advice.
