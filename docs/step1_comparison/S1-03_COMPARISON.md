# Comparison S1-03 — levothyroxine

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** Timing relative to breakfast, and the dosing interval from drugs that affect its absorption.
- **Fixed identity:** `1e11ad30-1041-4520-10b0-8f9d30d30fcc` version `1537`
- **Gold file:** `docs/step1_gold/S1-03_levothyroxine.md` (`2c894ebc15b1b3d73bd75658cade295b95cd87bc71f45656b26202f77791bc85`)
- **MCP case file:** `docs/step1_mcp_run/S1-03_levothyroxine.md` (`c3cc54b5a66387bd42b70ab5d50888e53a80897ce7c460f4ecf2cc1a796045a6`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-03_levothyroxine.json` (`5511b74921eaf18d23fe58ca8e1567ea9f581f445bea2e9b62178b3edc70e73c`)

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

- find_documents: 0.953 s | index: 0.621 s | slice: 0.654 s | verify: 0.955 s
- total automated: 6.693 s
- slice requested `['34068-7', '42229-5']`, not found `[]`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| Single daily dose on an empty stomach, one-half to one hour before breakfast. | MET | MCP: 'Single daily dose, on an empty stomach, one-half to one hour before breakfast.' |
| At least 4 hours before or after drugs known to interfere with absorption. | MET | MCP: 'At least 4 hours before or after drugs known to interfere with absorption.' |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: PASS

Gold verdict was **SUPPORTED**.

Both gold claims are answered from the same section at the same locator, and both MCP claims are carried by the slice text.

---

## Gold record, in full

# Gold record S1-03 — levothyroxine

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Timing relative to breakfast, and the dosing interval from drugs that affect its absorption.

## Identity

| field | value |
| --- | --- |
| set_id | `1e11ad30-1041-4520-10b0-8f9d30d30fcc` |
| version | `1537` |
| raw SPL path | `data/raw/dailymed/1e11ad30-1041-4520-10b0-8f9d30d30fcc/1537/label.xml` |
| expected raw SHA-256 | `de366bdd1a38c827eff6c082896ea88f8ffde929b647df38421f595d9437203a` |
| recomputed raw SHA-256 | `de366bdd1a38c827eff6c082896ea88f8ffde929b647df38421f595d9437203a` |
| digests agree | yes |
| sections in document | 60 |

## Evidence read from the document

### sequence 6 — 2.1 
 Important
 Administration 
 Instructions

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[1]/section[1]`

```text
Administer SYNTHROID as a single daily dose, on an empty stomach, one-half to one hour before breakfast. 

 
Administer SYNTHROID at least 4 hours before or after drugs known to interfere with SYNTHROID absorption [see Drug Interactions 
 (
 
 7.1
 
 )
 ]. 

 
Evaluate the need for dosage adjustments when regularly administering within one hour of certain foods that may affect SYNTHROID absorption [see 
 Dosage and Administration (
 
 2.2
 
 and 
 
 2.3
 
 ), 
 Drug Interactions 
 (
 
 7.9
 
 )
 ,
 and Clinical Pharmacology 
 (
 
 12.3
 
 )
 ]. 

 
Administer SYNTHROID to pediatric patients who cannot swallow intact tablets by crushing the tablet, suspending the freshly crushed tablet in a small amount (5 to 10 mL) of water and immediately administering the suspension by spoon or dropper. Ensure the patient ingests the full amount of the suspension. Do not store the suspension. Do not administer in foods that decrease absorption of SYNTHROID, such as soybean-based infant formula [see Drug Interactions 
 (
 
 7.9
 
 )
 ].
```

## Gold answer, and the quote supporting each statement

- **Single daily dose on an empty stomach, one-half to one hour before breakfast.**
  - supported by: `on an empty stomach, one-half to one hour before breakfast`
- **At least 4 hours before or after drugs known to interfere with absorption.**
  - supported by: `at least 4 hours before or after drugs known to interfere with SYNTHROID absorption`

## Verdict: SUPPORTED

Both halves of the question are stated in the same administration-instructions section.


---

## MCP output record, in full

# MCP run S1-03 — levothyroxine

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Timing relative to breakfast, and the dosing interval from drugs that affect its absorption.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-03_levothyroxine.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `1e11ad30-1041-4520-10b0-8f9d30d30fcc` |
| fixed version | `1537` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 415 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `de366bdd1a38c827eff6c082896ea88f8ffde929b647df38421f595d9437203a` |
| source_version returned | `1537` |
| effective_date returned | `2024-02-20` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/1e11ad30-1041-4520-10b0-8f9d30d30fcc.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "levothyroxine"}` | 0.953 |
| `odd_get_section_index` | `{"set_id": "1e11ad30-1041-4520-10b0-8f9d30d30fcc", "source_version": "1537"}` | 0.621 |
| `odd_get_evidence_slice` | `{"section_codes": ["34068-7", "42229-5"], "set_id": "1e11ad30-1041-4520-10b0-8f9d30d30fcc", "source_version": "1537"}` | 0.654 |
| `odd_verify_document` | `{"set_id": "1e11ad30-1041-4520-10b0-8f9d30d30fcc", "source_version": "1537"}` | 0.955 |
| *initialize* | — | 3.192 |

**Total automated processing time: 6.693 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['administration', 'absorption']`
- section codes selected: `['34068-7', '42229-5']`
- index sections matching those keywords: 2
- section_index carries no text: `False`
- sections in index: 60

## Slice returned

- requested codes: `['34068-7', '42229-5']`
- returned codes: `['34068-7', '42229-5']`
- sections returned: 20
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**2.1 Important Administration Instructions** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[1]/section[1]`
- section_sha256: `0829debdd8965acf9536ac549cb88a69476949b5266d3f499a9f25ec85c1d651`
- raw_sha256: `de366bdd1a38c827eff6c082896ea88f8ffde929b647df38421f595d9437203a`

```text
Administer SYNTHROID as a single daily dose, on an empty stomach, one-half to one hour before breakfast. Administer SYNTHROID at least 4 hours before or after drugs known to interfere with SYNTHROID absorption [see Drug Interactions ( 7.1 ) ]. Evaluate the need for dosage adjustments when regularly administering within one hour of certain foods that may affect SYNTHROID absorption [see Dosage and Administration ( 2.2 and 2.3 ), Drug Interactions ( 7.9 ) , and Clinical Pharmacology ( 12.3 ) ]. Administer SYNTHROID to pediatric patients who cannot swallow intact tablets by crushing the tablet, suspending the freshly crushed tablet in a small amount (5 to 10 mL) of water and immediately administering the suspension by spoon or dropper. Ensure the patient ingests the full amount of the suspension. Do not store the suspension. Do not administer in foods that decrease absorption of SYNTHROID, such as soybean-based infant formula [see Drug Interactions ( 7.9 ) ].
```

## ODD answer, composed from the slice only

- **Single daily dose, on an empty stomach, one-half to one hour before breakfast.**
  - from the slice: `Administer SYNTHROID as a single daily dose, on an empty stomach, one-half to one hour before breakfast.`
- **At least 4 hours before or after drugs known to interfere with absorption.**
  - from the slice: `Administer SYNTHROID at least 4 hours before or after drugs known to interfere with SYNTHROID absorption`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`

