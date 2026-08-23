# ODD core boundary

ODD's mainline is one path and nothing else:

```
official primary source
  -> preserved raw bytes + SHA-256
  -> sections extracted from those bytes
  -> structured output with source, version, and evidence locators
  -> re-verification of that output against the preserved bytes
```

Run it with `odd` (or `python -m odd`). That is the official and only ODD entry
point. The ODD-001..005 commands are retained under `odd-legacy`.

## What the core is responsible for

1. Preserve official primary sources exactly as issued.
2. Keep source, version, retrieval time, SHA-256, and evidence position traceable.
3. Return that content in a structured form an AI can consume.

## What the core does not do

It does not pick the correct drug, rank manufacturers or products, adjudicate
medical claims, guess missing facts, discard candidates, or run audits. When it
cannot know, it returns every candidate it saw, or `UNKNOWN`.

`odd fetch --drug Eliquis` returns all ten official candidates and stops.
Narrowing is the caller's decision, expressed as `--set-id` and
`--source-version`, and ODD only checks that the identity matches the official
response exactly.

## Mainline modules

| Responsibility | Module |
| --- | --- |
| retrieve | `odd.connectors.dailymed.client` |
| preserve raw + SHA-256 | `odd.provenance.raw_store`, `odd.provenance.hashing` |
| version and provenance | `odd.models.SourceIdentity`, the raw `metadata.json` |
| extract sections | `odd.parsers.spl.parser` |
| AI-facing output | `odd.core.evidence` |
| evidence locator | `odd.core.locator` |
| re-verification | `odd.core.pipeline.CorePipeline.verify` |
| complete listing retrieval | `odd.core.lookup` |
| entry point | `odd.core.cli` |

## Held aside

These still exist and still work. They are simply not reachable from the core
path, which `tests/core/test_core_boundary.py` enforces by pinning the core's
import closure:

- candidate selection and adjudication — `odd.connectors.dailymed.selection`,
  `odd.connectors.dailymed.batch_selection`, `odd.enrichment`
- batch and live observation runs — `odd.batch`, `odd.service`, `odd.storage`
- temporal diff and lineage — `odd.diffs`, `odd.versioning`, `odd.validation`
- ODD-006/007/007R research — `odd.cohort`, `odd.cohort_runner`,
  `odd.odd007_verification`, `odd.scope_guard`, `odd.governance`,
  `docs/research/`, `audit/`

These modules keep their current paths on purpose:
`docs/research/ODD-007_COMMIT_CANDIDATE_ALLOWLIST.json` records
`src/odd/cohort.py`, `src/odd/cohort_runner.py`, and
`src/odd/odd007_verification.py` by exact path, and
`src/odd/odd007_verification.py` reads `src/odd/constants.py`,
`src/odd/scope_guard.py`, `src/odd/storage/sqlite.py`, and
`src/odd/resources/us_top10_2023.json` by exact path. Relocating them would
invalidate those existing records, so the separation is enforced at the import
boundary instead of by moving files.

The core's import closure contains no selection, adjudication, enrichment,
cohort, batch, database, or research module, and no `sqlite3`. Three couplings
were removed to get there, none by deleting or moving anything:

- `odd.connectors.dailymed.__init__` re-exported `select_apixaban_candidate`
  eagerly; it now resolves on first attribute access.
- `odd.provenance.raw_store` imported `candidate_payload` from the selection
  module; that serializer now lives in `odd.connectors.dailymed.candidates`, and
  `selection` re-exports it.
- `odd.connectors.dailymed.client` imported the ODD-005 `CandidateDetailPage`
  model at module scope; it is now resolved inside the one method that builds it.

`odd.models` likewise resolves its batch re-exports on first use. Every legacy
name still imports exactly as before, which
`tests/core/test_core_boundary.py::test_the_held_aside_modules_still_work_when_asked_for_directly`
holds in place.

## Evidence locator

Every returned passage carries an `xml_locator` such as:

```
/document[1]/component[1]/structuredBody[1]/component[4]/section[1]/component[1]/section[1]
```

Each step is an XML local name plus its 1-based position among siblings sharing
that name. A consumer holding only the JSON can open `source.raw_path`, confirm
`source.raw_sha256`, resolve the locator, and recompute
`evidence.section_sha256` to prove the text it was handed is the passage the
locator addresses. The form deliberately depends on nothing but the stored
bytes — no database, no ODD identifiers, no ODD state.
