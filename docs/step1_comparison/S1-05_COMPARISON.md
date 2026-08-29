# Comparison S1-05 — amlodipine

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** The adult starting dose and maximum dose for hypertension.
- **Fixed identity:** `7367289c-b0b0-466a-83e2-558e2985c29f` version `10`
- **Gold file:** `docs/step1_gold/S1-05_amlodipine.md` (`f8fdd62a74a7a3fada01fb2bd706d50833cd23da96bd6ca816bd9c72084b1134`)
- **MCP case file:** `docs/step1_mcp_run/S1-05_amlodipine.md` (`7772298afc45107a6bd9403b1dff8c753d13de0f9768ae56648e35c51d170d32`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-05_amlodipine.json` (`e5fe644a7813f3b67f8feec6b128979f97bedc3a8b6d86c40606476f0dd14d1d`)

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

- find_documents: 0.768 s | index: 0.491 s | slice: 0.682 s | verify: 0.703 s
- total automated: 5.954 s
- slice requested `['34068-7', '42229-5']`, not found `[]`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| Usual initial antihypertensive oral dose 5 mg once daily. | MET | MCP: same. |
| Maximum dose 10 mg once daily. | MET | MCP: same. |
| Small, fragile, elderly, or hepatic-insufficiency patients may start at 2.5 mg once daily. | MET | MCP: same. |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: PASS

Gold verdict was **SUPPORTED**.

Every gold claim is answered from section 2.1 Adults at the same locator, and every MCP claim is carried by the slice text.

---

## Gold record, in full

# Gold record S1-05 — amlodipine

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and maximum dose for hypertension.

## Identity

| field | value |
| --- | --- |
| set_id | `7367289c-b0b0-466a-83e2-558e2985c29f` |
| version | `10` |
| raw SPL path | `data/raw/dailymed/7367289c-b0b0-466a-83e2-558e2985c29f/10/label.xml` |
| expected raw SHA-256 | `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51` |
| recomputed raw SHA-256 | `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51` |
| digests agree | yes |
| sections in document | 65 |

## Evidence read from the document

### sequence 9 — 2.1 Adults

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`

```text
The usual initial antihypertensive oral dose of NORVASC is 5 mg once daily, and the maximum dose is 10 mg once daily. 

 
Small, fragile, or elderly patients, or patients with hepatic insufficiency may be started on 2.5 mg once daily and this dose may be used when adding NORVASC to other antihypertensive therapy.

 
Adjust dosage according to blood pressure goals. In general, wait 7 to 14 days between titration steps. Titrate more rapidly, however, if clinically warranted, provided the patient is assessed frequently.

 

 Angina: The recommended dose for chronic stable or vasospastic angina is 5–10 mg, with the lower dose suggested in the elderly and in patients with hepatic insufficiency. Most patients will require 10 mg for adequate effect.

 

 Coronary artery disease: The recommended dose range for patients with coronary artery disease is 5–10 mg once daily. In clinical studies, the majority of patients required 10 mg [see Clinical Studies (14.4)].
```

## Gold answer, and the quote supporting each statement

- **Usual initial antihypertensive oral dose 5 mg once daily.**
  - supported by: `The usual initial antihypertensive oral dose of NORVASC is 5 mg once daily`
- **Maximum dose 10 mg once daily.**
  - supported by: `the maximum dose is 10 mg once daily`
- **Small, fragile, elderly, or hepatic-insufficiency patients may start at 2.5 mg once daily.**
  - supported by: `may be started on 2.5 mg once daily`

## Verdict: SUPPORTED

Section 2.1 Adults states the initial and maximum antihypertensive doses directly.


---

## MCP output record, in full

# MCP run S1-05 — amlodipine

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and maximum dose for hypertension.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-05_amlodipine.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `7367289c-b0b0-466a-83e2-558e2985c29f` |
| fixed version | `10` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 347 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51` |
| source_version returned | `10` |
| effective_date returned | `2023-02-15` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/7367289c-b0b0-466a-83e2-558e2985c29f.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "amlodipine"}` | 0.768 |
| `odd_get_section_index` | `{"set_id": "7367289c-b0b0-466a-83e2-558e2985c29f", "source_version": "10"}` | 0.491 |
| `odd_get_evidence_slice` | `{"section_codes": ["42229-5", "34068-7"], "set_id": "7367289c-b0b0-466a-83e2-558e2985c29f", "source_version": "10"}` | 0.682 |
| `odd_verify_document` | `{"set_id": "7367289c-b0b0-466a-83e2-558e2985c29f", "source_version": "10"}` | 0.703 |
| *initialize* | — | 3.068 |

**Total automated processing time: 5.954 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['dosage and administration', 'adult', 'hypertension']`
- section codes selected: `['42229-5', '34068-7']`
- index sections matching those keywords: 5
- section_index carries no text: `False`
- sections in index: 65

## Slice returned

- requested codes: `['34068-7', '42229-5']`
- returned codes: `['34068-7', '42229-5']`
- sections returned: 35
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**2.1 Adults** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`
- section_sha256: `997184a6ac290846da4b318c8837ee3d9acf4e0df942e6c4063897e7e0d296e3`
- raw_sha256: `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51`

```text
The usual initial antihypertensive oral dose of NORVASC is 5 mg once daily, and the maximum dose is 10 mg once daily. Small, fragile, or elderly patients, or patients with hepatic insufficiency may be started on 2.5 mg once daily and this dose may be used when adding NORVASC to other antihypertensive therapy. Adjust dosage according to blood pressure goals. In general, wait 7 to 14 days between titration steps. Titrate more rapidly, however, if clinically warranted, provided the patient is assessed frequently. Angina: The recommended dose for chronic stable or vasospastic angina is 5–10 mg, with the lower dose suggested in the elderly and in patients with hepatic insufficiency. Most patients will require 10 mg for adequate effect. Coronary artery disease: The recommended dose range for patients with coronary artery disease is 5–10 mg once daily. In clinical studies, the majority of patients required 10 mg [see Clinical Studies (14.4)].
```

## ODD answer, composed from the slice only

- **Usual initial antihypertensive oral dose 5 mg once daily.**
  - from the slice: `The usual initial antihypertensive oral dose of NORVASC is 5 mg once daily,`
- **Maximum dose 10 mg once daily.**
  - from the slice: `and the maximum dose is 10 mg once daily.`
- **Small, fragile, elderly, or hepatic-insufficiency patients may start at 2.5 mg once daily.**
  - from the slice: `Small, fragile, or elderly patients, or patients with hepatic insufficiency may be started on 2.5 mg once daily`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`

