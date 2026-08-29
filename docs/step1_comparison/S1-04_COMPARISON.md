# Comparison S1-04 — lisinopril

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** The contraindication on concomitant use with sacubitril/valsartan, and the washout interval required.
- **Fixed identity:** `838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8` version `2`
- **Gold file:** `docs/step1_gold/S1-04_lisinopril.md` (`110d0730154b28740a42d9c785c5aae22a6b6064c65a7eca516bf412e0119443`)
- **MCP case file:** `docs/step1_mcp_run/S1-04_lisinopril.md` (`66bc4a3f6ef9ef93346ab3869d1f6a5d87959987281937284a58c1990358b2df`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-04_lisinopril.json` (`33b0a3080d71e442b02c60b5ad949a06c5db8346e6865853a487db112df40346`)

## Required conditions

| condition | met |
| --- | --- |
| fixed identity returned by find_documents | yes |
| find_documents within 5 s | yes |
| ODD did not choose (selection_performed false) | yes |
| index contained the needed section | yes |
| slice returned the needed text | yes |
| verify succeeded | yes |
| total automated time within 15 s | yes |
| network attempts 0 | yes |
| data writes 0 | yes |
| no execution error | yes |

- find_documents: 0.802 s | index: 0.501 s | slice: 0.678 s | verify: 1.052 s
- total automated: 6.127 s
- slice requested `['34070-3', '34073-7']`, not found `[]`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| Contraindicated in combination with a neprilysin inhibitor such as sacubitril. | MET | MCP: same statement. |
| Do not administer within 36 hours of switching to or from sacubitril/valsartan. | MET | MCP: same statement, including the 36-hour interval. |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: PASS

Gold verdict was **SUPPORTED**.

Both gold claims are answered from section 34070-3 at the same locator, and both MCP claims are carried by the slice text.

---

## Gold record, in full

# Gold record S1-04 — lisinopril

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The contraindication on concomitant use with sacubitril/valsartan, and the washout interval required.

## Identity

| field | value |
| --- | --- |
| set_id | `838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8` |
| version | `2` |
| raw SPL path | `data/raw/dailymed/838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8/2/label.xml` |
| expected raw SHA-256 | `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa` |
| recomputed raw SHA-256 | `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa` |
| digests agree | yes |
| sections in document | 61 |

## Evidence read from the document

### sequence 14 — 4 CONTRAINDICATIONS

- **section code:** `34070-3` (CONTRAINDICATIONS SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]`

```text
Zestril is contraindicated in combination with a neprilysin inhibitor (e.g., sacubitril). Do not administer Zestril within 36 hours of switching to or from sacubitril/valsartan, a neprilysin inhibitor [
 see Warnings and Precautions (5.2)].

 
Zestril is contraindicated in patients with:

 

 
a history of angioedema or hypersensitivity related to previous treatment with an angiotensin converting enzyme inhibitor

 
hereditary or idiopathic angioedema

 

 
Do not co-administer aliskiren with ZESTRIL in patients with diabetes [see
 
 Drug Interactions (7.4)
 
 ].
```

## Gold answer, and the quote supporting each statement

- **Contraindicated in combination with a neprilysin inhibitor such as sacubitril.**
  - supported by: `contraindicated in combination with a neprilysin inhibitor (e.g., sacubitril)`
- **Do not administer within 36 hours of switching to or from sacubitril/valsartan.**
  - supported by: `Do not administer Zestril within 36 hours of switching to or from sacubitril/valsartan`

## Verdict: SUPPORTED

The contraindications section states both the contraindication and the 36-hour interval.


---

## MCP output record, in full

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

