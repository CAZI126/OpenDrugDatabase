# ODD over MCP

## What this is for

An AI client usually cannot answer a drug question from a label safely, because
the whole label is too large to read and a summary of it is no longer evidence.
ODD's MCP server exists so the client can work the other way round: see what a
preserved document contains, ask for the few sections it actually needs, and
receive each passage with the position it was taken from and the digest that
proves it was not altered.

**ODD transports primary sources. It does not make medical judgements.** It
returns official labeling, the FDA record linked to it by exact application
identity, and the exact location every passage came from. Deciding what any of
that means for a patient is the reader's responsibility, not ODD's.

Two rules matter more than any feature here:

- **ODD never chooses between matching documents.** If a name matches several
  preserved labels, all of them come back and the caller names the one it wants.
- **Nothing is invented.** What the sources do not state is reported as
  `UNKNOWN`, and anything that cannot be established at all comes back as a
  structured error rather than a plausible-looking answer.

The server is a caller of `odd.core`, not a second implementation. Every answer
comes from the same pipeline the `odd` command line drives, so the two cannot
drift into disagreeing about what a document says.

**Every tool reads, and only reads.** No tool call retrieves anything over the
network, and none writes into the data root. That includes Drugs@FDA: the archive
is consulted only where one is already preserved, and having none to read is
reported as `NOT_PRESERVED`, which is a different answer from the archive being
read and not naming the application, which is `NOT_FOUND`. Retrieval stays where
it was always explicit — the CLI:

```console
odd extract --set-id <id> --include-drugsfda
```

## Installation

The MCP SDK is an optional extra, so a normal install stays dependency-free:

```console
python -m pip install -e ".[mcp]"
```

## Starting the server

The server speaks MCP over stdio and retrieves nothing on its own — it reads the
documents already preserved under the data root:

```console
odd catalog build --data-dir data
odd catalog verify --data-dir data
python -m odd.mcp --data-dir data
```

Build the catalog explicitly after preserving or adding documents.
`odd_find_documents` reads `catalog/manifest.json` and
`catalog/documents.jsonl` only; it never parses label XML, writes a catalog, or
falls back to a corpus scan during an MCP call. The catalog is a deterministic,
rebuildable derivative and is not primary evidence. `catalog_freshness` is
therefore reported as `NOT_CHECKED_DURING_QUERY`; the explicit verify command
performs the raw-manifest count and identity-fingerprint comparison. Missing,
invalid, and unsupported catalogs return `CATALOG_NOT_BUILT`, `CATALOG_INVALID`,
and `CATALOG_SCHEMA_UNSUPPORTED`, respectively, with the build command in the
error guidance.

`odd-mcp --data-dir data` is the same entry point as a console script, and
`ODD_DATA_DIR` is used when `--data-dir` is omitted. To preserve a document for
the server to serve, use the existing CLI first:

```console
odd run --drug Eliquis --set-id e9481622-7cc6-418a-acb6-c5450daae9b0
```

### Over HTTP, on this machine only

The same four tools are also served over MCP's streamable HTTP transport, for
clients that speak HTTP rather than stdio:

```console
python -m odd.mcp --http --data-dir data
```

The endpoint is `http://127.0.0.1:8765/mcp`. It binds loopback by design, and
`--host`/`--port` change that: binding anything else publishes an
**unauthenticated** server, because no authentication is implemented here. The
entry point says so on stderr when you do it.

Only the transport differs. The HTTP app is built from the same `create_server`
and the same read-only tool surface the stdio server uses, so nothing is
reachable over HTTP that is not reachable over a pipe -- there is no retrieval,
update or delete tool on either. DNS-rebinding protection is on and scoped to the
bound loopback address, so a page served from another origin cannot drive the
server by pointing at localhost.

A client configuration entry looks like this:

```json
{
  "mcpServers": {
    "odd": {
      "command": "python",
      "args": ["-m", "odd.mcp", "--data-dir", "/path/to/data"]
    }
  }
}
```

## Tools

### `odd_find_documents`

Which preserved documents could this question be about?

| input | type | required |
| --- | --- | --- |
| `query` | string | yes |

Matches the query, case-insensitively, against what each preserved document
states about itself: title, brand names, generic name, active ingredients.

Returns `candidate_count` and a `candidates` array. Each candidate carries
`set_id`, `source_version`, `document_title`, `brand_names`, `generic_name`,
`active_ingredients`, `effective_date`, `label_publisher`, `label_repository`,
`jurisdiction`, `source_url`, `raw_sha256`, and `raw_path`. `selection_performed`
is always `false`: several matches means several results, never a pick.

### `odd_get_section_index`

What is in the document, without reading it?

| input | type | required |
| --- | --- | --- |
| `set_id` | string | yes |
| `source_version` | string | only when several versions are preserved |

Returns one entry per section with `section_code`, `section_title`,
`content_status`, `text_length`, `depth`, `sequence_index`,
`parent_sequence_index` (the subsection relationship), `evidence_locator`,
`section_sha256`, and `text_sha256`.

`carries_section_text` is `false` and the entries have no text field. A digest
cannot be read back into the passage it covers, so the index stays free of the
document's words while remaining checkable against them.

### `odd_get_evidence_slice`

Read only the sections you named.

| input | type | required |
| --- | --- | --- |
| `set_id` | string | yes |
| `section_codes` | array of string | yes |
| `application_number` | string | no |
| `source_version` | string | only when several versions are preserved |

Section codes are matched **exactly**. A parent section is never widened to its
subsections, so `subsections_added_implicitly` is `false` and
`unexpected_section_codes` is empty. A code the document does not state appears
in `section_codes_not_found` and is never fabricated.

Each returned section carries `section_code`, `section_title`, `text`, and an
`evidence` block with `xml_locator`, `section_sha256`, `text_sha256`, `raw_path`,
and `raw_sha256`. The `document` block carries the source URL, version, effective
date, publisher, jurisdiction, and raw digest.

Supplying `application_number` also returns the Drugs@FDA record under
`drugs_fda`, linked by **exact application-number identity only** — brand name,
ingredient, and sponsor never create a link, and a prefix or a bare number is a
different application. `drugs_fda.status` distinguishes three things, and
`network_attempted` is always `false`:

| status | what it means |
| --- | --- |
| `EXACT` | the preserved archive names this application under this identity |
| `NOT_FOUND` | the archive was read and names no such application |
| `NOT_PRESERVED` | no archive is preserved here, so there was nothing to read |
| `UNKNOWN` | no `application_number` was supplied, so FDA was not consulted |

### `odd_verify_document`

Does any of it still hold up against the preserved bytes?

| input | type | required |
| --- | --- | --- |
| `set_id` | string | yes |
| `application_number` | string | no |
| `source_version` | string | only when several versions are preserved |

Re-hashes the preserved raw source, re-resolves every section anchor against it,
and re-checks source and version consistency. Returns `result` as `VERIFIED` or
`FAILED`, the individual `checks`, and `failure_reasons`.

Naming an `application_number` carries the same re-verification through to the
FDA link, so a slice and a verification cannot disagree about it. `drugs_fda_linkage`
then reports `archive_path`, `archive_sha256_expected` against
`archive_sha256_actual`, `exact_match_status`, `matched_application_number`, each
cited row's `zip_member`, `row_number` and `row_sha256`, and its own `result`.
With no archive preserved, that half is `NOT_PRESERVED` and the label's own
verification stands on its own rather than being dragged down with it.

Bytes that no longer agree with their own immutable manifest are reported as
`FAILED` — that is the answer this tool exists to give. Only having nothing to
verify is an error.

## Worked example: Eliquis

Preserve the document once with the CLI, then drive the four tools in order.

**1. Find it.**

```json
{"name": "odd_find_documents", "arguments": {"query": "apixaban"}}
```

```json
{
 "candidate_count": 1,
 "selection_performed": false,
 "candidates": [{
   "set_id": "e9481622-7cc6-418a-acb6-c5450daae9b0",
   "source_version": "30",
   "effective_date": "2025-04-17",
   "label_repository": "DailyMed",
   "jurisdiction": "United States",
   "raw_sha256": "d6549bce...e101e1aa",
   "source_url": "https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/e9481622-7cc6-418a-acb6-c5450daae9b0.xml"
 }]
}
```

**2. See what it contains.**

```json
{"name": "odd_get_section_index",
 "arguments": {"set_id": "e9481622-7cc6-418a-acb6-c5450daae9b0"}}
```

**3. Take only the sections you need, with the FDA record.**

```json
{"name": "odd_get_evidence_slice",
 "arguments": {"set_id": "e9481622-7cc6-418a-acb6-c5450daae9b0",
               "section_codes": ["34067-9", "34071-1"],
               "application_number": "NDA202155"}}
```

`returned_section_codes` holds those two codes and nothing else;
`drugs_fda.status` is `EXACT`, and every FDA row carries its `zip_member`,
`row_number`, `row_sha256`, and the archive's own digest.

**4. Re-verify.**

```json
{"name": "odd_verify_document",
 "arguments": {"set_id": "e9481622-7cc6-418a-acb6-c5450daae9b0",
               "application_number": "NDA202155"}}
```

The preserved label is re-hashed, all 88 anchors are re-resolved from it, the
preserved FDA archive is re-hashed, and the cited rows are re-read from it by
member and row number — all without a single retrieval.

## Tests

```console
python -m pytest tests/mcp -q
```

`tests/mcp/test_tools.py` covers the tool surface, `tests/mcp/test_protocol.py`
drives the whole Eliquis question through a real MCP client session,
`tests/mcp/test_stdio_entry.py` starts `python -m odd.mcp` as a process and
speaks JSON-RPC to it, and `tests/mcp/test_offline.py` runs the whole surface
with connections off this machine refused at the socket, comparing the data root
file by file and digest by digest before and after every call. All of them run
from committed fixtures with no network access.
