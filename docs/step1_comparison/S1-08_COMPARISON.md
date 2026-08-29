# Comparison S1-08 — losartan

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** The adult starting dose and maximum dose for hypertension, and the starting dose in patients with intravascular volume depletion.
- **Fixed identity:** `9949448f-c3b9-44ee-94ed-c1aca8c90f39` version `9`
- **Gold file:** `docs/step1_gold/S1-08_losartan.md` (`947dc2510b9424d055170e0625bf29110d669957b8ed7efc23fb86951f1da12f`)
- **MCP case file:** `docs/step1_mcp_run/S1-08_losartan.md` (`45bca036951a1eb1da8d5242d3a93bccbc9f79d0a1084cc4d2b2184ec183128b`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-08_losartan.json` (`d3cbc44b2411809e9c75209d71c41e38a726dc1177c90defe024358f47b3ed68`)

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

- find_documents: 0.715 s | index: 0.52 s | slice: 0.604 s | verify: 1.039 s
- total automated: 5.999 s
- slice requested `['34068-7', '42229-5']`, not found `[]`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| Usual starting dose 50 mg once daily. | MET | MCP: same. |
| Maximum dose 100 mg once daily. | MET | MCP: same. |
| Starting dose 25 mg where intravascular depletion is possible. | MET | MCP: same. |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: PASS

Gold verdict was **SUPPORTED**.

All three gold claims are answered from the same untitled subsection at the same locator. The index and slice report its section_title as UNKNOWN, which matches the document stating none; the passage was still retrieved and carries the answer.

---

## Gold record, in full

# Gold record S1-08 — losartan

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and maximum dose for hypertension, and the starting dose in patients with intravascular volume depletion.

## Identity

| field | value |
| --- | --- |
| set_id | `9949448f-c3b9-44ee-94ed-c1aca8c90f39` |
| version | `9` |
| raw SPL path | `data/raw/dailymed/9949448f-c3b9-44ee-94ed-c1aca8c90f39/9/label.xml` |
| expected raw SHA-256 | `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f` |
| recomputed raw SHA-256 | `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f` |
| digests agree | yes |
| sections in document | 78 |

## Evidence read from the document

### sequence 9 — (section states no title)

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]/component[1]/section[1]/component[1]/section[1]`

```text
Adult Hypertension
 

 
The usual starting dose of COZAAR is 50 mg once daily. The dosage can be increased to a maximum dose of 100 mg once daily as needed to control blood pressure [see Clinical Studies (14.1)]. A starting dose of 25 mg is recommended for patients with possible intravascular depletion (e.g., on diuretic therapy).
```

## Gold answer, and the quote supporting each statement

- **Usual starting dose 50 mg once daily.**
  - supported by: `The usual starting dose of COZAAR is 50 mg once daily.`
- **Maximum dose 100 mg once daily.**
  - supported by: `increased to a maximum dose of 100 mg once daily`
- **Starting dose 25 mg where intravascular depletion is possible.**
  - supported by: `A starting dose of 25 mg is recommended for patients with possible intravascular depletion`

## Verdict: SUPPORTED

One untitled subsection under 2.1 Hypertension states all three figures.

**Note on this document:** This section element carries no <title> child; 'Adult Hypertension' is the first line of its text.


---

## MCP output record, in full

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

