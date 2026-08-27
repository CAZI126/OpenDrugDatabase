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

## Installation

The MCP SDK is an optional extra, so a normal install stays dependency-free:

```console
python -m pip install -e ".[mcp]"
```

## Starting the server

The server speaks MCP over stdio and retrieves nothing on its own — it reads the
documents already preserved under the data root:

```console
python -m odd.mcp --data-dir data
```

`odd-mcp --data-dir data` is the same entry point as a console script, and
`ODD_DATA_DIR` is used when `--data-dir` is omitted. To preserve a document for
the server to serve, use the existing CLI first:

```console
odd run --drug Eliquis --set-id e9481622-7cc6-418a-acb6-c5450daae9b0
```

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
ingredient, and sponsor never create a link. Omitting it leaves
`drugs_fda.status` as `UNKNOWN`, because not asking FDA is not the same as
asking and finding nothing.

### `odd_verify_document`

Does any of it still hold up against the preserved bytes?

| input | type | required |
| --- | --- | --- |
| `set_id` | string | yes |
| `source_version` | string | only when several versions are preserved |

Re-hashes the preserved raw source, re-resolves every section anchor against it,
re-checks source and version consistency, and re-verifies the Drugs@FDA linkage
when the bundle carries one. Returns `result` as `VERIFIED` or `FAILED`, the
individual `checks`, and `failure_reasons`.

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
 "arguments": {"set_id": "e9481622-7cc6-418a-acb6-c5450daae9b0"}}
```

## Tests

```console
python -m pytest tests/mcp -q
```

`tests/mcp/test_tools.py` covers the tool surface, `tests/mcp/test_protocol.py`
drives the whole Eliquis question through a real MCP client session, and
`tests/mcp/test_stdio_entry.py` starts `python -m odd.mcp` as a process and
speaks JSON-RPC to it. All of them run from committed fixtures with no network
access.
