# MCP run S1-02 — metformin

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Starting, continuation, and discontinuation criteria based on eGFR.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-02_metformin.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `c82a10fa-1e8e-46b6-890a-737de3f34ee1` |
| fixed version | `17` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 550 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| source_version returned | `17` |
| effective_date returned | `2026-07-15` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/c82a10fa-1e8e-46b6-890a-737de3f34ee1.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "metformin"}` | 0.959 |
| `odd_get_section_index` | `{"set_id": "c82a10fa-1e8e-46b6-890a-737de3f34ee1", "source_version": "17"}` | 0.589 |
| `odd_get_evidence_slice` | `{"section_codes": ["UNKNOWN", "34070-3"], "set_id": "c82a10fa-1e8e-46b6-890a-737de3f34ee1", "source_version": "17"}` | 0.744 |
| `odd_verify_document` | `{"set_id": "c82a10fa-1e8e-46b6-890a-737de3f34ee1", "source_version": "17"}` | 1.097 |
| *initialize* | — | 3.263 |

**Total automated processing time: 6.914 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['renal', 'egfr', 'contraindication']`
- section codes selected: `['UNKNOWN', '34070-3']`
- index sections matching those keywords: 3
- section_index carries no text: `False`
- sections in index: 45

## Slice returned

- requested codes: `['34070-3', 'UNKNOWN']`
- returned codes: `['34070-3']`
- sections returned: 1
- codes not found: `['UNKNOWN']`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**4 CONTRAINDICATIONS** — code `34070-3`

- locator: `/document[1]/component[1]/structuredBody[1]/component[7]/section[1]`
- section_sha256: `cbbd0a9a2d87f3c7d464dd5b2fbde968d404da68deedcbd9ad2de3ed61b4d74f`
- raw_sha256: `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d`

```text
Metformin hydrochloride tablets are contraindicated in patients with: Severe renal impairment (eGFR below 30 mL/min/1.73 m2) [see Warnings and Precautions (5.1)]. Hypersensitivity to metformin. Acute or chronic metabolic acidosis, including diabetic ketoacidosis, with or without coma.
```

## ODD answer, composed from the slice only

- **Contraindicated in severe renal impairment, eGFR below 30 mL/min/1.73 m2.**
  - from the slice: `Severe renal impairment (eGFR below 30 mL/min/1.73 m2) [see Warnings and Precautions (5.1)].`
- **Starting criteria at eGFR 30 to 45: UNKNOWN from this slice.**
  - from the slice: `NOT RETURNED: the index reported the renal-recommendations section with section_code UNKNOWN; requesting that code returned section_codes_not_found ['UNKNOWN'] and no text.`
- **Continuation criteria when eGFR later falls below 45: UNKNOWN from this slice.**
  - from the slice: `NOT RETURNED: same section could not be retrieved.`
- **Discontinuation criteria when eGFR later falls below 30: UNKNOWN from this slice.**
  - from the slice: `NOT RETURNED: same section could not be retrieved. Only the contraindication threshold was retrievable.`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`
