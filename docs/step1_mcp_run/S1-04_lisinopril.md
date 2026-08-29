# MCP run S1-04 — lisinopril

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The contraindication on concomitant use with sacubitril/valsartan, and the washout interval required.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-04_lisinopril.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8` |
| fixed version | `2` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 376 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa` |
| source_version returned | `2` |
| effective_date returned | `2025-01-02` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "lisinopril"}` | 0.802 |
| `odd_get_section_index` | `{"set_id": "838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8", "source_version": "2"}` | 0.501 |
| `odd_get_evidence_slice` | `{"section_codes": ["34070-3", "34073-7"], "set_id": "838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8", "source_version": "2"}` | 0.678 |
| `odd_verify_document` | `{"set_id": "838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8", "source_version": "2"}` | 1.052 |
| *initialize* | — | 2.84 |

**Total automated processing time: 6.127 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['contraindication', 'neprilysin', 'sacubitril']`
- section codes selected: `['34070-3', '34073-7']`
- index sections matching those keywords: 2
- section_index carries no text: `False`
- sections in index: 61

## Slice returned

- requested codes: `['34070-3', '34073-7']`
- returned codes: `['34070-3', '34073-7']`
- sections returned: 10
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**4 CONTRAINDICATIONS** — code `34070-3`

- locator: `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]`
- section_sha256: `0ccea203058e7a85bc056fa9cc57942b4fe3e6b7881814ee2e7aa3e4b7f41e16`
- raw_sha256: `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa`

```text
Zestril is contraindicated in combination with a neprilysin inhibitor (e.g., sacubitril). Do not administer Zestril within 36 hours of switching to or from sacubitril/valsartan, a neprilysin inhibitor [ see Warnings and Precautions (5.2)]. Zestril is contraindicated in patients with: a history of angioedema or hypersensitivity related to previous treatment with an angiotensin converting enzyme inhibitor hereditary or idiopathic angioedema Do not co-administer aliskiren with ZESTRIL in patients with diabetes [see Drug Interactions (7.4) ].
```

## ODD answer, composed from the slice only

- **Contraindicated in combination with a neprilysin inhibitor such as sacubitril.**
  - from the slice: `Zestril is contraindicated in combination with a neprilysin inhibitor (e.g., sacubitril).`
- **Do not administer within 36 hours of switching to or from sacubitril/valsartan.**
  - from the slice: `Do not administer Zestril within 36 hours of switching to or from sacubitril/valsartan, a neprilysin inhibitor`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`
