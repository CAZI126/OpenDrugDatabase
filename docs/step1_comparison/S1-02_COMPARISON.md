# Comparison S1-02 — metformin

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** Starting, continuation, and discontinuation criteria based on eGFR.
- **Fixed identity:** `c82a10fa-1e8e-46b6-890a-737de3f34ee1` version `17`
- **Gold file:** `docs/step1_gold/S1-02_metformin.md` (`e39dcb19aee04005fdb54fb83bbad87c3e06b38277cd904361411e74ca304145`)
- **MCP case file:** `docs/step1_mcp_run/S1-02_metformin.md` (`fb347064ad4c0c4b5368ed275e46078b549c3fb7abd1149eaf5f987ff4db763a`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-02_metformin.json` (`5037b55dd04a24d0260f8a8f96bb5dc74819129501e653066cf531e396e84b96`)

## Required conditions

| condition | met |
| --- | --- |
| fixed identity returned by find_documents | yes |
| find_documents within 5 s | yes |
| ODD did not choose (selection_performed false) | yes |
| index contained the needed section | yes |
| slice returned the needed text | **no** |
| verify succeeded | yes |
| total automated time within 15 s | yes |
| network attempts 0 | yes |
| data writes 0 | yes |
| no execution error | yes |

- find_documents: 0.959 s | index: 0.589 s | slice: 0.744 s | verify: 1.097 s
- total automated: 6.914 s
- slice requested `['34070-3', 'UNKNOWN']`, not found `['UNKNOWN']`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| Contraindicated below eGFR 30 mL/minute/1.73 m2. | MET | MCP: 'Contraindicated in severe renal impairment, eGFR below 30 mL/min/1.73 m2.' |
| Initiation is not recommended at eGFR 30 to 45 mL/minute/1.73 m2. | **MISSING** | MCP answered UNKNOWN: the section carrying it could not be retrieved. |
| If eGFR later falls below 45, assess the benefit risk of continuing. | **MISSING** | MCP answered UNKNOWN: same section could not be retrieved. |
| Discontinue if eGFR later falls below 30. | **MISSING** | MCP answered UNKNOWN: same section could not be retrieved. |
| Assess renal function before initiation and periodically thereafter. | **MISSING** | MCP answered nothing on this point; the section was not retrieved. |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: FAIL

Gold verdict was **SUPPORTED**.

The gold is SUPPORTED: the document states all four eGFR criteria in section 2.3. ODD could not deliver them. The index reported that section with section_code UNKNOWN, and requesting that code returned section_codes_not_found ['UNKNOWN'] with no text, so four of five gold claims are unanswered. Under the frozen protocol this is 'required text is missing' and is FAIL. It is not read as UNKNOWN or VALID_UNKNOWN: the document does state the answer, and the failure to reach it is ODD's, not the document's.

---

## Gold record, in full

# Gold record S1-02 — metformin

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Starting, continuation, and discontinuation criteria based on eGFR.

## Identity

| field | value |
| --- | --- |
| set_id | `c82a10fa-1e8e-46b6-890a-737de3f34ee1` |
| version | `17` |
| raw SPL path | `data/raw/dailymed/c82a10fa-1e8e-46b6-890a-737de3f34ee1/17/label.xml` |
| expected raw SHA-256 | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| recomputed raw SHA-256 | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| digests agree | yes |
| sections in document | 45 |

## Evidence read from the document

### sequence 8 — 2.3 Recommendations for Use in Renal Impairment

- **section code:** (section states no code)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[3]/section[1]`

```text
Assess renal function prior to initiation of metformin hydrochloride tablets and periodically thereafter.

 
Metformin hydrochloride tablets are contraindicated in patients with an estimated glomerular filtration rate (eGFR) below 30 mL/minute/1.73 m2.

 
Initiation of metformin hydrochloride tablets in patients with an eGFR between 30 mL/minute/1.73 m2to 45 mL/minute/1.73 m2is not recommended.

 
In patients taking metformin hydrochloride tablets whose eGFR later falls below 45 mL/min/1.73 m2, assess the benefit risk of continuing therapy.

 
Discontinue metformin hydrochloride tablets if the patient's eGFR later falls below 30 mL/minute/1.73 m2
 [
 s
 ee Warnings and Precautions (5.1)].
```

### sequence 11 — 4 CONTRAINDICATIONS

- **section code:** `34070-3` (CONTRAINDICATIONS SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[7]/section[1]`

```text
Metformin hydrochloride tablets are contraindicated in patients with:

 

 
Severe renal impairment (eGFR below 30 mL/min/1.73 m2) [see Warnings and Precautions (5.1)].

 
Hypersensitivity to metformin.

 
Acute or chronic metabolic acidosis, including diabetic ketoacidosis, with or without coma.
```

## Gold answer, and the quote supporting each statement

- **Contraindicated below eGFR 30 mL/minute/1.73 m2.**
  - supported by: `contraindicated in patients with an estimated glomerular filtration rate (eGFR) below 30`
- **Initiation is not recommended at eGFR 30 to 45 mL/minute/1.73 m2.**
  - supported by: `Initiation of metformin hydrochloride tablets in patients with an eGFR between 30`
- **If eGFR later falls below 45, assess the benefit risk of continuing.**
  - supported by: `whose eGFR later falls below 45 mL/min/1.73 m2, assess the benefit risk of continuing therapy`
- **Discontinue if eGFR later falls below 30.**
  - supported by: `Discontinue metformin hydrochloride tablets if the patient's eGFR later falls below 30`
- **Assess renal function before initiation and periodically thereafter.**
  - supported by: `Assess renal function prior to initiation`

## Verdict: SUPPORTED

Section 2.3 states all four eGFR thresholds; the contraindications section corroborates the below-30 threshold.

**Note on this document:** The 2.3 section element carries no <code> child in this document. Recorded as stated, not filled in.


---

## MCP output record, in full

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

