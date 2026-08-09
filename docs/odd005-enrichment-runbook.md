# ODD-005 DailyMed candidate-enrichment runbook

Checked against the official DailyMed and FDA Structured Product Labeling (SPL)
documentation on 2026-08-09. An enrichment run is a bounded observation of official data at
retrieval time. It is not a permanent currentness guarantee or clinical validation.

## Purpose and safety boundary

ODD-005 attaches structured official evidence to candidates retained by an immutable ODD-004
discovery snapshot. It may revise a candidate decision only after every potentially competitive
candidate is proven eligible or proven ineligible. `UNKNOWN`, conflicting evidence, source drift,
an incomplete request budget, and an authoritative tie all stop automatic selection.

The goal is evidence preservation, not manufacturing a winner. A selected SPL is one technical
validation label. It does not represent every formulation, route, manufacturer, product, or
patient population for the ranked ingredient. ODD is not a clinically validated database and its
output must not be used directly for medical decisions.

ODD-004 source databases, discovery responses, manifests, and reports are immutable parent
evidence. Run ODD-005 only in a new ignored local directory containing a hash-checked copy or a
new database that retains the complete parent records. Never point enrichment at the sole retained
parent database.

## Official contract checked

Only these official sources were used to define extraction rules:

- [DailyMed web-services overview](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)
- [DailyMed `/spls` search API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_api.cfm)
- [DailyMed set-ID packaging API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_packaging_api.cfm)
- [DailyMed set-ID current XML API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_api.cfm)
- [DailyMed set-ID history API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_history_api.cfm)
- [DailyMed individual SPL downloads](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)
- [DailyMed bulk SPL downloads](https://dailymed.nlm.nih.gov/dailymed/spl-resources-all-drug-labels.cfm)
- [FDA SPL implementation guide](https://www.fda.gov/media/84201/download?attachment=)
- [FDA SPL document types](https://www.fda.gov/industry/structured-product-labeling-resources/document-type-including-content-labeling-type)
- [FDA SPL business-operation codes](https://www.fda.gov/industry/structured-product-labeling-resources/business-operation)

Confirmed facts used by ODD-005:

- `GET /dailymed/services/v2/spls/{SETID}/packaging.json` accepts `page` and `pagesize`;
  the documented default and maximum page size are 100.
- Packaging JSON documents the response `setid`, `spl_version`, title, publication date,
  products, package descriptions, and structured `active_ingredients` names and strengths.
- The packaging response documentation does not define a total-element or total-page field.
  ODD therefore requests contiguous pages through a short terminal page, rejects repeated product
  identities and inconsistent set/version metadata, and never estimates an omitted total.
- `GET /dailymed/services/v2/spls/{SETID}.xml` returns the current SPL XML for a set ID. It does
  not document a source-version request parameter. ODD accepts those bytes only when structured
  `setId` and `versionNumber` equal the parent candidate; otherwise it records `SOURCE_DRIFT`.
- The reviewed XML documentation does not specify an `Accept` request value. A bounded live
  contract check on 2026-08-09 observed HTTP 406 for `Accept: application/xml` and HTTP 200 with
  `Content-Type: application/xml` for `Accept: */*` at that official endpoint. The connector
  therefore uses the neutral wildcard and still rejects any non-XML Content-Type or body before
  retaining source bytes.
- DailyMed history is a separate set-ID endpoint. The official individual-download interface
  documents an explicit version parameter for older ZIP retrieval. ODD-005 does not silently
  substitute a current document for a historical candidate.
- FDA SPL defines `setId` as stable across revisions and `versionNumber` as the document version.
- FDA SPL active-ingredient class codes `ACTIB`, `ACTIM`, and `ACTIR` are evaluated. Their
  `ingredientSubstance/name` is kept distinct from a nested `activeMoiety/name` and any reference
  substance. Inactive ingredient text, titles, product names, and brand names are not
  ingredient-identity evidence.
- FDA document codes `34391-3` and `34390-5` identify human prescription and human OTC labels;
  `50578-4` and `50577-6` identify prescription and OTC animal drug labels. ODD's versioned
  extractor distinguishes the human/animal and prescription/OTC axes for these reviewed codes.
- FDA business-operation codes `C73606` and `C73607` positively identify repackaging or
  relabeling when present in the reviewed structured locator.
- Bulk archives are separate corpus downloads and are not used by ODD-005.

Not confirmed by the reviewed official detail contract and therefore not inferred:

- a packaging field that proves a product is *not* repackaged or relabeled;
- a guaranteed packaging total-count field;
- a documented numeric request quota or rate limit;
- guaranteed ETag or Last-Modified headers;
- a packaging field that independently proves route, dosage form, marketing category, or
  veterinary status for the selection policy;
- chemical equivalence between a ranked name and a salt, ester, hydrate, complex, isomer,
  formulation, synonym, or active moiety;
- absence of a repack/relabel code as proof of a non-repackaged product.

These facts remain `UNKNOWN`. If another official source is required to prove them, adding that
source and a versioned mapping policy is a later design decision, not an ODD-005 inference.

## Evidence tiers

Tier 0 reuses the complete ODD-004 search snapshot. Its documented human-prescription filter and
current-SPL API scope support only those corresponding assertions. Unsupported search fields stay
`UNKNOWN`.

Tier 1 fetches small packaging JSON pages by set ID before any SPL XML. Exact response bytes,
SHA-256, canonical request, request and final URLs, status, Content-Type, ETag, Last-Modified,
retrieval time, attempt evidence, expected version, observed version, candidate ID, and parent
discovery snapshot are retained. Structured active-ingredient arrays may prove a combination,
single ingredient, or exact lexical ingredient name. No chemical mapping is applied.

Tier 2 is optional and separately capped. It is considered only for candidates that remain
potentially competitive after Tier 1. SPL XML extraction evaluates structured document identity,
document code, active-ingredient class/name elements, and positive repack/relabel codes. DTD or
entity declarations are rejected before parsing. Retrieved XML is cached as exact evidence and,
if ultimately selected, is promoted to the existing raw store and ingested without re-download.

Tier 3 revises the decision and invokes existing ingest, parser-compatibility, normalization,
SQLite, document verification, and artifact verification only for a unique supported winner.

## Four-valued assertions and completeness

Every assertion is `PROVEN_TRUE`, `PROVEN_FALSE`, `UNKNOWN`, or `CONFLICT`. It retains its
candidate/set/version identity, parent discovery snapshot, enrichment run and snapshot, every
exact source-response hash (plus the singular hash when one response is sufficient), official
source URL identity, JSON Pointer or XML locator, source field/code, extraction-rule
version, extractor version, diagnostic, and operational retrieval time. Operational time is not
part of canonical evidence or report identity.

Contradictory non-UNKNOWN assertions collapse to `CONFLICT`; ODD never chooses the favorable one.
An enrichment decision is complete only when:

1. the parent discovery is complete;
2. every candidate is proven ineligible or has every required eligibility assertion;
3. no candidate has source drift or conflicting evidence;
4. no unresolved candidate could outrank a proposed winner;
5. numeric source version and publication date exist for every eligible candidate; and
6. exactly one candidate has the highest authoritative version/date score.

Response order, enrichment queue order, and lexical set ID are not tie-breakers. An authoritative
tie remains `MANUAL_REVIEW_REQUIRED`. Earlier ODD-004 decisions and every ODD-005 decision revision
are immutable history records.

## Snapshot, cache, resume, and source drift

One enrichment snapshot identity is derived from ordered parent discovery snapshot IDs, sorted
exact response identities and SHA-256 values, sorted canonical assertion identities, extractor
version, and extraction-rule version. Retrieval timestamps, local paths, execution tokens,
observation tokens, and cache counters do not change it.

Successful response identities are immutable. Reusing an identity with different exact bytes is
rejected. A terminal run returns its stored report without network traffic. A budget-partial run
may be resumed with a new explicit execution budget; completed candidate pages and XML are cache
hits and are not downloaded again. A new observation creates a new enrichment run and never
overwrites an earlier run or decision revision.

Set-ID mismatch, version mismatch, a packaging publication-date mismatch, an off-origin redirect,
a Content-Type/body mismatch, or a raw
identity conflict cannot be merged into the parent candidate. Structured set/version mismatch is
`SOURCE_DRIFT` and requires a new ODD-004 discovery observation or an explicitly designed
version-specific retrieval path.

## HTTP operating policy and mandatory budgets

Every live plan and execution requires explicit values for maximum requests, maximum downloaded
bytes, timeout, retry limit, inter-request delay, maximum response bytes, maximum detail pages,
and maximum Tier-2 candidates. There is no unlimited default.

ODD uses verified HTTPS, serial requests, a project/version User-Agent, an allowed DailyMed origin,
and same-origin redirect validation. It distinguishes permanent 4xx from 429 and transient 5xx,
honors valid `Retry-After`, and applies bounded exponential backoff. Each response is read with a
hard size sentinel; partial or oversized bytes do not become successful evidence. Content-Type and
the JSON/XML representation are validated. TLS verification is never disabled.

The reviewed DailyMed pages do not publish a numeric rate limit. A local delay and hard budget are
a conservative ODD policy, not a statement of an official quota. Operators must stop on repeated
429 responses or service-use concerns rather than increase limits automatically.

## Read-only plan, rank-1 canary, and resume

Use a durable ignored directory copied from the verified ODD-004 parent. Global storage arguments
must precede `enrichment`. The SHA passed to `--parent-database-sha256` is the parent database hash
recorded before the copy is migrated to schema v5.

```powershell
$Pilot = (Resolve-Path .\data).Path + "\live\odd005-canary-<YYYYMMDD>"
$Database = "$Pilot\database\odd.sqlite3"
$ParentRun = "<ODD004_LIVE_RUN_ID>"
$ParentDatabaseSha256 = "<HASH_OF_IMMUTABLE_ODD004_DATABASE>"

odd --data-dir $Pilot --database $Database enrichment plan `
  --parent-run $ParentRun --ranks 1 `
  --max-requests 806 --max-bytes 220000000 --timeout 30 `
  --retry-limit 1 --rate-delay 0.30 --max-response-bytes 262144 `
  --max-detail-pages 2 --max-tier2-candidates 0

odd --data-dir $Pilot --database $Database enrichment run `
  --parent-run $ParentRun --new-observation --ranks 1 `
  --parent-database-sha256 $ParentDatabaseSha256 --max-tier 1 `
  --max-requests 806 --max-bytes 220000000 --timeout 30 `
  --retry-limit 1 --rate-delay 0.30 --max-response-bytes 262144 `
  --max-detail-pages 2 --max-tier2-candidates 0
```

The numbers above illustrate an explicit canary envelope; they are not universal defaults. Inspect
the plan's candidate count, unique set IDs, minimum/maximum requests, maximum byte reservation,
endpoint list, and minimum delay before authorizing live access.

If an execution stops at its budget, resume only the same run ID. New explicit limits apply to that
execution segment and cannot erase earlier evidence:

```powershell
odd --data-dir $Pilot --database $Database enrichment run `
  --resume <ENRICHMENT_RUN_ID> --max-tier 1 `
  --max-requests 806 --max-bytes 220000000 --timeout 30 `
  --retry-limit 1 --rate-delay 0.30 --max-response-bytes 262144 `
  --max-detail-pages 2 --max-tier2-candidates 0

odd --data-dir $Pilot --database $Database enrichment status --run <ENRICHMENT_RUN_ID>
odd --data-dir $Pilot --database $Database enrichment evidence `
  --run <ENRICHMENT_RUN_ID> --rank 1
odd --data-dir $Pilot --database $Database enrichment decisions `
  --run <ENRICHMENT_RUN_ID> --rank 1
odd --data-dir $Pilot --database $Database enrichment report `
  --run <ENRICHMENT_RUN_ID> --format text --output "$Pilot\reports\report.txt"
odd --data-dir $Pilot --database $Database enrichment report `
  --run <ENRICHMENT_RUN_ID> --format json --output "$Pilot\reports\report.json"
odd --data-dir $Pilot --database $Database enrichment verify --run <ENRICHMENT_RUN_ID>
```

Do not expand from rank 1 unless Tier 1 materially reduces the candidate set, all extraction rules
match the official contract, cache-only resume and artifact verification pass, service behavior is
polite, and the next explicit hard budget is acceptable. If Tier 1 leaves most candidates unknown
and resolving them would require thousands of full SPL documents, stop. Do not convert that result
into an unbounded XML crawl.

## Storage and reports

Schema v5 additively retains enrichment runs and executions, snapshots, detail responses,
assertions, item states, decision revisions, and artifacts. v1-v4 tables and parent evidence are
not rewritten. Filesystem evidence is stored below:

```text
data/live/<ignored-odd005-pilot>/
|-- database/odd.sqlite3
|-- evidence/dailymed/enrichment/responses/{response_id}/
|   |-- response.body
|   `-- evidence.json
|-- evidence/dailymed/enrichment/snapshots/{snapshot_id}/
|   |-- manifest.json
|   `-- manifest.sha256
|-- raw/dailymed/{set_id}/{source_version}/
`-- reports/
```

The canonical JSON report excludes operational timestamps, local absolute paths, observation and
execution tokens, and cache-only counters. It reports each ingredient's parent snapshot, candidate
counts, Tier 0/1/2 progress, eligibility results, unknown/conflict/drift counts, completeness,
selection, selected identity, transport totals, ingest/parser/verification states, and artifact
hash. The text report presents the same safety states for human review.

CI is fully offline. Synthetic official-shape fixtures test extraction, pagination, budgets,
retry, drift, resume, immutability, and tamper detection; they are not retained DailyMed evidence
or claims about current live products. Live databases, exact responses, XML, reports, and logs stay
under ignored local data paths and are never Git fixtures.
