# ODD core boundary

ODD's mainline is one path and nothing else:

```
official primary source
  -> preserved raw bytes + SHA-256
  -> sections extracted from those bytes
  -> structured output with source, version, and evidence locators
  -> re-verification of that output against the preserved bytes
```

Run it with `odd-core` (or `python -m odd.core`).

## What the core is responsible for

1. Preserve official primary sources exactly as issued.
2. Keep source, version, retrieval time, SHA-256, and evidence position traceable.
3. Return that content in a structured form an AI can consume.

## What the core does not do

It does not pick the correct drug, rank manufacturers or products, adjudicate
medical claims, guess missing facts, discard candidates, or run audits. When it
cannot know, it returns every candidate it saw, or `UNKNOWN`.

`odd-core fetch --drug Eliquis` returns all ten official candidates and stops.
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

The core reaches three off-core modules, none of which carries a rule:
`odd.models.batch` and `odd.models.enrichment` are dataclass definitions
re-exported by `odd.models`, and `odd.connectors.dailymed.selection` is reached
only for its `candidate_payload` serializer, which `odd.provenance.raw_store`
already depended on.

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
