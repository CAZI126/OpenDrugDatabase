# OpenDrugDatabase

OpenDrugDatabase (ODD) is an open-source version-control foundation for global regulatory drug
knowledge. Regulatory source documents are primary data. Normalized mappings and temporal diffs
are reproducible derivative data that retain traceability to exact source bytes.

## Implemented scope: ODD-001 and ODD-002

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
python -m pytest tests\parsers\test_spl_parser.py::test_repeated_parsing_is_byte_deterministic
python -m pytest tests\diffs\test_genuine_temporal_diff.py::test_canonical_diff_is_timestamp_independent_and_idempotent
```

CI runs these checks independently on Python 3.12.

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
- Live fetch depends on DailyMed availability and its response contract; CI is fully offline.
- Broader redistribution and licensing questions for DailyMed collections are unresolved. Only
  two focused source-version fixtures are retained here for reproducible verification.
- EMA, PMDA, cross-regulatory comparison, REST/API changes, SDK, Web UI, AI/LLM/MCP changes,
  alerting, scheduling, corpus synchronization, and community features are intentionally deferred.

ODD is not yet a complete FDA, EMA, or PMDA database. Normalized ODD data and generated diffs are
not substitutes for the official regulatory source and are not medical advice.
