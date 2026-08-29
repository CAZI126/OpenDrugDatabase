# MCP run S1-06 — metoprolol

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Identify this document's salt, immediate- or extended-release, and dosage form; then give the adult starting dose for hypertension.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-06_metoprolol.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `b5f4fed2-369c-4808-a682-8a5b8cfdbb4f` |
| fixed version | `3` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 470 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e` |
| source_version returned | `3` |
| effective_date returned | `2026-01-26` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/b5f4fed2-369c-4808-a682-8a5b8cfdbb4f.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "metoprolol"}` | 0.875 |
| `odd_get_section_index` | `{"set_id": "b5f4fed2-369c-4808-a682-8a5b8cfdbb4f", "source_version": "3"}` | 0.442 |
| `odd_get_evidence_slice` | `{"section_codes": ["34067-9", "34068-7", "43678-2", "34070-3"], "set_id": "b5f4fed2-369c-4808-a682-8a5b8cfdbb4f", "source_version": "3"}` | 0.426 |
| `odd_verify_document` | `{"set_id": "b5f4fed2-369c-4808-a682-8a5b8cfdbb4f", "source_version": "3"}` | 0.791 |
| *initialize* | — | 2.885 |

**Total automated processing time: 5.683 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['dosage forms', 'dosage and administration', 'indications', 'hypertension']`
- section codes selected: `['34067-9', '34068-7', '43678-2', '34070-3']`
- index sections matching those keywords: 4
- section_index carries no text: `False`
- sections in index: 47

## Slice returned

- requested codes: `['34067-9', '34068-7', '34070-3', '43678-2']`
- returned codes: `['34067-9', '34068-7', '34070-3', '43678-2']`
- sections returned: 4
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**3 DOSAGE FORMS AND STRENGTHS** — code `43678-2`

- locator: `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]`
- section_sha256: `8fb69f03a03b62c1899d15ee178dd438f7db024b488b8ce642aa56727019882d`
- raw_sha256: `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e`

```text
LOPRESSOR is supplied as a 12.5 mg tablet that is pink-colored, film coated, round, biconvex, debossed with “˄E” on one side, and plain on the other side.
```

## ODD answer, composed from the slice only

- **Salt: metoprolol tartrate.**
  - from the slice: `document block: generic_name METOPROLOL TARTRATE; document_title '... LOPRESSOR ®(metoprolol tartrate) tablets, for oral use ...'`
- **Dosage form: 12.5 mg film-coated tablet.**
  - from the slice: `LOPRESSOR is supplied as a 12.5 mg tablet that is pink-colored, film coated, round, biconvex`
- **Immediate- or extended-release: UNKNOWN from this slice.**
  - from the slice: `NOT RETURNED: no returned section states a release characteristic for this product.`
- **Adult starting dose for hypertension: UNKNOWN from this slice.**
  - from the slice: `NOT RETURNED: '1 INDICATIONS AND USAGE' and '2 DOSAGE AND ADMINISTRATION' were returned with 0 characters of text, and no returned section states a hypertension dose.`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`
