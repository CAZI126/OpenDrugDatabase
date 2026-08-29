# Comparison S1-06 — metoprolol

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** Identify this document's salt, immediate- or extended-release, and dosage form; then give the adult starting dose for hypertension.
- **Fixed identity:** `b5f4fed2-369c-4808-a682-8a5b8cfdbb4f` version `3`
- **Gold file:** `docs/step1_gold/S1-06_metoprolol.md` (`163263a3ce354db2f74de1210e9654f1b9de68d969cfc669378186e6103ed3b9`)
- **MCP case file:** `docs/step1_mcp_run/S1-06_metoprolol.md` (`a9f043e834a9ac01aea884b5d5f22f1cb60ebd073317b1715f2b373158501de2`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-06_metoprolol.json` (`a4d65a4fc882ffed57446898db2d3d7103804f8ceae1a9070459eb51319ba63e`)

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

- find_documents: 0.875 s | index: 0.442 s | slice: 0.426 s | verify: 0.791 s
- total automated: 5.683 s
- slice requested `['34067-9', '34068-7', '34070-3', '43678-2']`, not found `[]`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| Salt: metoprolol tartrate. | MET | MCP: 'Salt: metoprolol tartrate.', from the document block and title. |
| Dosage form: film-coated tablet, 12.5 mg. | MET | MCP: 'Dosage form: 12.5 mg film-coated tablet.', from section 43678-2. |
| Release characteristic: the document does not state one for this product. | MET | MCP answered UNKNOWN and named what was not returned. |
| Adult starting dose for hypertension: not stated anywhere in this document. | MET | MCP answered UNKNOWN and named what was not returned. |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: VALID_UNKNOWN

Gold verdict was **VALID_UNKNOWN**.

The gold is VALID_UNKNOWN: the pinned identity is a myocardial-infarction-only Lopressor label with no hypertension indication and no hypertension dosing. ODD stopped at UNKNOWN for the release characteristic and the hypertension dose rather than supplying either from outside the document, which is the required behaviour. Under the frozen protocol VALID_UNKNOWN does not count toward the pass total.

---

## Gold record, in full

# Gold record S1-06 — metoprolol

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Identify this document's salt, immediate- or extended-release, and dosage form; then give the adult starting dose for hypertension.

## Identity

| field | value |
| --- | --- |
| set_id | `b5f4fed2-369c-4808-a682-8a5b8cfdbb4f` |
| version | `3` |
| raw SPL path | `data/raw/dailymed/b5f4fed2-369c-4808-a682-8a5b8cfdbb4f/3/label.xml` |
| expected raw SHA-256 | `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e` |
| recomputed raw SHA-256 | `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e` |
| digests agree | yes |
| sections in document | 47 |

## Evidence read from the document

### sequence 3 — 1.1 Myocardial Infarction

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[2]/section[1]/component[1]/section[1]`

```text
LOPRESSOR is indicated in the treatment of hemodynamically stable adult patients with myocardial infarction (MI) to reduce cardiovascular mortality.
```

### sequence 5 — 2.1 Myocardial Infarction

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`

```text
The recommended starting dose in hemodynamically stable patients is 50 mg orally every 6 hours. In case of intolerance, reduce the starting dose to 25 mg orally every 6 hours and administer for 48 hours. Titrate dosage based on tolerability and hemodynamic parameters (i.e., heart rate, blood pressure). LOPRESSOR should preferably be administered with or following meals. The maximum daily maintenance dosage is 100 mg orally twice daily.
```

### sequence 6 — 3 DOSAGE FORMS AND STRENGTHS

- **section code:** `43678-2` (DOSAGE FORMS & STRENGTHS SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]`

```text
LOPRESSOR is supplied as a 12.5 mg tablet that is pink-colored, film coated, round, biconvex, debossed with “˄E” on one side, and plain on the other side.
```

## Gold answer, and the quote supporting each statement

- **Salt: metoprolol tartrate.**
  - supported by: `DOCUMENT TITLE: LOPRESSOR ®(metoprolol tartrate) tablets, for oral use`
- **Dosage form: film-coated tablet, 12.5 mg.**
  - supported by: `LOPRESSOR is supplied as a 12.5 mg tablet that is pink-colored, film coated`
- **Release characteristic: the document does not state one for this product.**
  - supported by: `ABSENT: 'extended-release' appears 0 times; 'immediate-release' appears only in 12.3 Pharmacokinetics and the CYP2D6 interaction discussion, describing immediate-release metoprolol generally, not this product's dosage form.`
- **Adult starting dose for hypertension: not stated anywhere in this document.**
  - supported by: `ABSENT: the sole indication is 1.1 Myocardial Infarction and the sole adult dosing is 2.1 Myocardial Infarction. 'hypertension' occurs twice, both describing clonidine rebound hypertension in drug interactions, never as an indication.`

## Verdict: VALID_UNKNOWN

The salt and dosage form are stated and were read out of the document. The adult hypertension starting dose is genuinely absent: this is a myocardial-infarction-only label. The question as asked cannot be answered from this pinned document, so the case is VALID_UNKNOWN and does not count toward the pass total. This is a property of the caller-supplied identity, not of ODD.


---

## MCP output record, in full

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

