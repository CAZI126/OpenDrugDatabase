# MCP run S1-01 — atorvastatin

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and the dose range.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-01_atorvastatin.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `a60cc18b-0631-4cf0-b021-9f52224ece65` |
| fixed version | `8` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 403 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `c6748f079a3cf15a3d9fe19dde9012fb62746cd68ea8e21506daab8d6f2a32fd` |
| source_version returned | `8` |
| effective_date returned | `2024-04-15` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/a60cc18b-0631-4cf0-b021-9f52224ece65.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "atorvastatin"}` | 1.092 |
| `odd_get_section_index` | `{"set_id": "a60cc18b-0631-4cf0-b021-9f52224ece65", "source_version": "8"}` | 1.497 |
| `odd_get_evidence_slice` | `{"section_codes": ["34068-7", "42229-5"], "set_id": "a60cc18b-0631-4cf0-b021-9f52224ece65", "source_version": "8"}` | 1.051 |
| `odd_verify_document` | `{"set_id": "a60cc18b-0631-4cf0-b021-9f52224ece65", "source_version": "8"}` | 1.739 |
| *initialize* | — | 6.588 |

**Total automated processing time: 12.317 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['dosage and administration', 'recommended dosage', 'adult']`
- section codes selected: `['34068-7', '42229-5']`
- index sections matching those keywords: 4
- section_index carries no text: `False`
- sections in index: 68

## Slice returned

- requested codes: `['34068-7', '42229-5']`
- returned codes: `['34068-7', '42229-5']`
- sections returned: 35
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**2.2 Recommended Dosage in Adult Patients** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[2]/section[1]`
- section_sha256: `9c584e1513ffba20cc8170e3e42a88d00e094f813a3e292cc88553cb8bc8e9d6`
- raw_sha256: `c6748f079a3cf15a3d9fe19dde9012fb62746cd68ea8e21506daab8d6f2a32fd`

```text
The recommended starting dosage of LIPITOR is 10 mg to 20 mg once daily. The dosage range is 10 mg to 80 mg once daily. Patients who require reduction in LDL-C greater than 45% may be started at 40 mg once daily.
```

## ODD answer, composed from the slice only

- **Starting dosage 10 mg to 20 mg once daily.**
  - from the slice: `The recommended starting dosage of LIPITOR is 10 mg to 20 mg once daily.`
- **Dosage range 10 mg to 80 mg once daily.**
  - from the slice: `The dosage range is 10 mg to 80 mg once daily.`
- **Patients needing more than 45% LDL-C reduction may start at 40 mg once daily.**
  - from the slice: `Patients who require reduction in LDL-C greater than 45% may be started at 40 mg once daily.`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`
