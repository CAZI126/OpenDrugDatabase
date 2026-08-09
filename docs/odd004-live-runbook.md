# ODD-004 DailyMed live observation runbook

Checked against the official DailyMed documentation on 2026-08-09. ODD-004 observes the
current API; it does not create a permanent guarantee that an observation remains current.

## Purpose and safety boundary

ODD-004 applies the fixed `us-top10-2023` rank-only input to the official DailyMed service. It
retains every candidate-discovery page as exact bytes, proves pagination completeness, classifies
all candidates under the versioned ODD policy, and downloads SPL XML only for a unique supported
winner. Ambiguity and missing metadata are successful safety outcomes when represented as
`MANUAL_REVIEW_REQUIRED`.

One selected label is one technical validation input. It is not representative of every dosage
form, route, manufacturer, product, or patient population for an ingredient. `FULLY_PARSED` means
only that the current parser detected no empty or unmapped sections. Neither status proves clinical
validity. ODD is not a clinically validated database and must not be used directly for medical
decisions.

## Official API contract checked

Only these official DailyMed pages were used as API-contract sources:

- [Web services overview](https://dailymed.nlm.nih.gov/dailymed/app-support-web-services.cfm)
- [`/spls` search API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_api.cfm)
- [`/spls/{SETID}.xml` API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_api.cfm)
- [`/spls/{SETID}/history` API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_history_api.cfm)
- [`/spls/{SETID}/packaging` API v2](https://dailymed.nlm.nih.gov/dailymed/webservices-help/v2/spls_setid_packaging_api.cfm)
- [Bulk SPL downloads](https://dailymed.nlm.nih.gov/dailymed/spl-resources-all-drug-labels.cfm)
- [About DailyMed and current-labeling caveat](https://dailymed.nlm.nih.gov/dailymed/about-dailymed.cfm)

Confirmed facts:

- `GET /dailymed/services/v2/spls.json` supports `drug_name`, `name_type`, `doctype`, `pagesize`,
  and `page`. The documented maximum `pagesize` is 100.
- ODD sends the generic-name filter and document type `34391-3` (human prescription drug label),
  with `pagesize=100`, then follows numbered pages serially.
- Search metadata documents `total_elements`, `elements_per_page`, `total_pages`, and
  `current_page`. Search result objects document `setid`, `spl_version`, `title`, and
  `published_date`.
- The web-services overview describes the v2 service as current SPL information and documents
  HTTPS GET requests plus normal 404, 415, and 5xx categories.
- Current SPL XML is retrieved with `GET /dailymed/services/v2/spls/{SETID}.xml`.
- History is a separate set-ID endpoint. The archive download path can request an explicit older
  version after history establishes that version.
- Bulk archives are separate downloads, substantially broader than individual API observations,
  and are not used by ODD-004.

Not confirmed in the official search-response contract and therefore stored as `UNKNOWN` rather
than inferred:

- active ingredient list and proof that the result is a single-ingredient product;
- dosage form and route;
- labeler and marketing category;
- repackaged status;
- a per-result archived flag beyond the documented current-API scope;
- a numeric rate limit or quota;
- a redirect policy;
- ETag or Last-Modified availability guarantees.

The packaging endpoint documents active-ingredient information, but it is not the `/spls` search
response and does not establish every field required by the ODD selection policy. ODD-004 does not
join unsupported assumptions across endpoints. If the live search response contains only its four
documented candidate fields, the candidate is retained and classified, but automatic selection is
withheld for missing single-ingredient, repackager, and related evidence.

## Snapshot identity and resume

A snapshot covers one normalized ingredient query and all successfully retained numbered pages.
Its UUIDv5 identity is derived from the canonical endpoint/query, connector version, ordered page
numbers and exact response SHA-256 values, plus a deterministic terminal-failure fingerprint when
discovery is incomplete. Retrieval time, filesystem path, and database path are excluded.

Consequences:

- identical exact responses produce the same snapshot ID;
- any changed response bytes, including byte-level result reordering, produce a new exact-evidence
  snapshot;
- candidate evidence is always sorted by stable metadata before classification, so response order
  alone cannot manufacture a different winner;
- one explicit `--new-observation` creates a new operational run and may reuse identical immutable
  snapshot evidence;
- `--resume` and phase commands with `--run` never issue candidate-search requests;
- an interrupted item without a completed snapshot becomes `DISCOVERY_INCOMPLETE`; obtaining new
  live bytes requires another explicit observation;
- exact page files and manifests are created once, hash-verified, and never overwritten.

## Pagination completeness

Automatic selection is allowed only when all of these checks pass:

1. every metadata count is an actual non-negative base-10 integer (page numbers and page size must
   also be positive, and page size must not exceed 100);
2. `current_page` equals the requested page;
3. totals and page size remain identical across pages;
4. `total_pages` is mathematically compatible with total elements and page size;
5. every advertised page returns a valid JSON object and candidate array;
6. retained candidate count equals `total_elements`;
7. no duplicate candidate identity appears between pages;
8. one set ID does not carry conflicting metadata.

Malformed, Boolean, floating-point, non-finite, negative, or missing counts are never coerced or
estimated. A failed page, count mismatch, duplicate, or conflict yields `DISCOVERY_INCOMPLETE` or
`INVALID`, and the selection policy returns `MANUAL_REVIEW_REQUIRED` with no winner.

## HTTP and XML operating policy

ODD uses verified HTTPS, an explicit 30-second timeout, serial requests, a 200 ms inter-page delay,
and `OpenDrugDatabase/0.4.0` identification. It retries 429 and transient 5xx responses at most two
times, records every attempt, honors a usable `Retry-After`, and otherwise uses capped exponential
backoff. Permanent 4xx responses are not retried. Redirects must remain on the configured scheme,
host, and effective port.

JSON responses are limited to 8 MiB and XML to 64 MiB. Content-Type and Content-Length are checked.
Obviously non-XML bytes declared as XML are rejected. Full SPL parsing rejects DTD/entity
declarations, does not expand external entities, validates set ID and version, and quarantines
malformed or unsupported exact raw evidence. A partial response with a mismatched Content-Length is
not accepted as a formal raw source.

The official pages reviewed above do not publish a numeric API rate limit. The local limits are a
conservative ODD operating policy, not a statement of a DailyMed quota.

## Live pilot commands

Use an ignored, durable workspace directory rather than the OS temporary directory. Global storage
options must precede `batch`:

```powershell
$Pilot = (Resolve-Path .\data).Path + "\live\odd004-pilot-20260808"
$Database = "$Pilot\database\odd.sqlite3"

odd --data-dir $Pilot --database $Database batch plan `
  --list us-top10-2023 --new-observation
```

Record the returned live run ID and inspect all ten decisions before later phases:

```powershell
$RunId = "<LIVE_BATCH_RUN_ID>"
odd --data-dir $Pilot --database $Database batch plan --resume $RunId
odd --data-dir $Pilot --database $Database batch fetch --run $RunId
odd --data-dir $Pilot --database $Database batch ingest --run $RunId
odd --data-dir $Pilot --database $Database batch verify --run $RunId
odd --data-dir $Pilot --database $Database batch status --run $RunId

odd --data-dir $Pilot --database $Database batch report --run $RunId `
  --format text --output "$Pilot\reports\report.txt"
odd --data-dir $Pilot --database $Database batch report --run $RunId `
  --format json --output "$Pilot\reports\report.json"
```

`batch run --run $RunId` is the combined fetch/ingest/verify/report operation. Manual-review items
are never forced and do not trigger XML downloads. `status` exposes retry eligibility and isolated
per-ingredient errors. `candidates --ingredient <name>` shows retained classification evidence;
ODD-004 intentionally provides no force-winner option.

The ignored pilot tree contains:

```text
data/live/odd004-pilot-20260808/
|-- database/odd.sqlite3
|-- evidence/dailymed/discovery/{snapshot_id}/
|   |-- page-NNNN.response
|   |-- manifest.json
|   `-- manifest.sha256
|-- raw/dailymed/{set_id}/{spl_version}/
|-- quarantine/
`-- reports/
```

Reports contain per-ingredient query, snapshot ID, advertised and retained counts, eligibility,
selection/manual-review status, set/version, raw hash, ingestion/parser/verification status, error
category, retry eligibility, and diagnostics. Aggregates include completeness, selection, manual
review, no-candidate, fetch/parser failure, verified/unresolved totals, final state, artifact hash,
and every versioned policy component.

CI is deliberately offline. It uses synthetic official-shape responses to test pagination,
network failures, resume, determinism, and integrity without converting a changing external service
into a build dependency. Live results are observations at their retrieval time, not committed
fixtures, a DailyMed mirror, or proof of permanent currentness. Regulatory response bytes, the
SQLite database, and generated reports remain in the ignored local pilot tree; a published SHA-256
value alone cannot reconstruct those bytes or let a third party verify them without access to the
same retained artifacts.
