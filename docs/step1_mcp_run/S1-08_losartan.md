# MCP run S1-08 — losartan

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and maximum dose for hypertension, and the starting dose in patients with intravascular volume depletion.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-08_losartan.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `9949448f-c3b9-44ee-94ed-c1aca8c90f39` |
| fixed version | `9` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 307 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f` |
| source_version returned | `9` |
| effective_date returned | `2026-01-20` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/9949448f-c3b9-44ee-94ed-c1aca8c90f39.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "losartan"}` | 0.715 |
| `odd_get_section_index` | `{"set_id": "9949448f-c3b9-44ee-94ed-c1aca8c90f39", "source_version": "9"}` | 0.52 |
| `odd_get_evidence_slice` | `{"section_codes": ["42229-5", "34068-7"], "set_id": "9949448f-c3b9-44ee-94ed-c1aca8c90f39", "source_version": "9"}` | 0.604 |
| `odd_verify_document` | `{"set_id": "9949448f-c3b9-44ee-94ed-c1aca8c90f39", "source_version": "9"}` | 1.039 |
| *initialize* | — | 2.884 |

**Total automated processing time: 5.999 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['dosage and administration', 'hypertension']`
- section codes selected: `['42229-5', '34068-7']`
- index sections matching those keywords: 4
- section_index carries no text: `False`
- sections in index: 78

## Slice returned

- requested codes: `['34068-7', '42229-5']`
- returned codes: `['34068-7', '42229-5']`
- sections returned: 47
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**UNKNOWN** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]/component[1]/section[1]/component[1]/section[1]`
- section_sha256: `f47824e5f11a5d074e96327b5ab466d47e7cbf799dcc1f687c1af16d3bf8ef9e`
- raw_sha256: `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f`

```text
Adult Hypertension The usual starting dose of COZAAR is 50 mg once daily. The dosage can be increased to a maximum dose of 100 mg once daily as needed to control blood pressure [see Clinical Studies (14.1)]. A starting dose of 25 mg is recommended for patients with possible intravascular depletion (e.g., on diuretic therapy).
```

## ODD answer, composed from the slice only

- **Usual starting dose 50 mg once daily.**
  - from the slice: `The usual starting dose of COZAAR is 50 mg once daily.`
- **Maximum dose 100 mg once daily.**
  - from the slice: `The dosage can be increased to a maximum dose of 100 mg once daily as needed to control blood pressure`
- **Starting dose 25 mg where intravascular depletion is possible.**
  - from the slice: `A starting dose of 25 mg is recommended for patients with possible intravascular depletion (e.g., on diuretic therapy).`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`
