# Comparison S1-07 — albuterol

Gold and MCP output are both frozen. Neither was re-run or edited to produce this.

- **Question:** The dosing interval, the maximum frequency of use, and the label's warning when more frequent use than usual becomes necessary.
- **Fixed identity:** `d92c5d6b-ff10-4087-36a2-1cfc464cb967` version `30`
- **Gold file:** `docs/step1_gold/S1-07_albuterol.md` (`1cce62f055e08a6482c203fa3357effc5e290ea75ce82767a1158b639f6bd7b4`)
- **MCP case file:** `docs/step1_mcp_run/S1-07_albuterol.md` (`a05a05df9f09bac251bf5879e7d78800fb84bfefc705abff26866a205f24b1f4`)
- **MCP raw output:** `docs/step1_mcp_run/raw/S1-07_albuterol.json` (`4fd724e635310860ab0a3f70d152b60d429b9ca0a3766a630551818d37c1af88`)

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

- find_documents: 0.731 s | index: 0.512 s | slice: 0.542 s | verify: 0.91 s
- total automated: 5.823 s
- slice requested `['34068-7', '42229-5', '43685-7']`, not found `[]`, unexpected `[]`
- verify: `VERIFIED` (raw `VERIFIED`, anchors `VERIFIED`)
- network attempts 0, data tree identical True

## Claim-by-claim

| gold claim | status | what MCP returned |
| --- | --- | --- |
| 2 inhalations every 4 to 6 hours; 1 inhalation every 4 hours may suffice in some patients. | MET | MCP: same. |
| More frequent administration or more inhalations is not recommended. | MET | MCP: same. |
| Needing more doses than usual may mark destabilization of asthma and requires reevaluation. | MET | MCP: same, from section 5.2. |

**MCP statements beyond the gold claims:** none.


## Provisional verdict: PASS

Gold verdict was **SUPPORTED**.

All three gold claims are answered, across the same two sections and locators the gold cites, and every MCP claim is carried by the slice text.

---

## Gold record, in full

# Gold record S1-07 — albuterol

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The dosing interval, the maximum frequency of use, and the label's warning when more frequent use than usual becomes necessary.

## Identity

| field | value |
| --- | --- |
| set_id | `d92c5d6b-ff10-4087-36a2-1cfc464cb967` |
| version | `30` |
| raw SPL path | `data/raw/dailymed/d92c5d6b-ff10-4087-36a2-1cfc464cb967/30/label.xml` |
| expected raw SHA-256 | `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2` |
| recomputed raw SHA-256 | `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2` |
| digests agree | yes |
| sections in document | 47 |

## Evidence read from the document

### sequence 6 — 2.1 Recommended Dosage for Bronchospasm (Acute Episodes or Symptoms Associated with Bronchospasm)

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`

```text
Adult and pediatric patients aged 4 years and older: 2 inhalations by oral inhalation repeated every 4 to 6 hours; in some patients, 1 inhalation every 4 hours may be sufficient. More frequent administration or a greater number of inhalations is not recommended.
```

### sequence 13 — 5.2 Deterioration of Asthma

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]/component[2]/section[1]`

```text
Asthma may deteriorate acutely over a period of hours or chronically over several days or longer. If the patient needs more doses of VENTOLIN HFA than usual, this may be a marker of destabilization of asthma and requires reevaluation of the patient and treatment regimen, giving special consideration to the possible need for anti-inflammatory treatment, e.g., corticosteroids.
```

## Gold answer, and the quote supporting each statement

- **2 inhalations every 4 to 6 hours; in some patients 1 inhalation every 4 hours may suffice.**
  - supported by: `2 inhalations by oral inhalation repeated every 4 to 6 hours; in some patients, 1 inhalation every 4 hours may be sufficient`
- **More frequent administration or more inhalations is not recommended.**
  - supported by: `More frequent administration or a greater number of inhalations is not recommended.`
- **Needing more doses than usual may mark destabilization of asthma and requires reevaluation.**
  - supported by: `If the patient needs more doses of VENTOLIN HFA than usual, this may be a marker of destabilization of asthma and requires reevaluation`

## Verdict: SUPPORTED

Dosing interval and maximum frequency are in 2.1; the warning on more frequent need is in 5.2.


---

## MCP output record, in full

# MCP run S1-07 — albuterol

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The dosing interval, the maximum frequency of use, and the label's warning when more frequent use than usual becomes necessary.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-07_albuterol.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `d92c5d6b-ff10-4087-36a2-1cfc464cb967` |
| fixed version | `30` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 192 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2` |
| source_version returned | `30` |
| effective_date returned | `2024-04-26` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/d92c5d6b-ff10-4087-36a2-1cfc464cb967.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "albuterol"}` | 0.731 |
| `odd_get_section_index` | `{"set_id": "d92c5d6b-ff10-4087-36a2-1cfc464cb967", "source_version": "30"}` | 0.512 |
| `odd_get_evidence_slice` | `{"section_codes": ["34068-7", "42229-5", "43685-7"], "set_id": "d92c5d6b-ff10-4087-36a2-1cfc464cb967", "source_version": "30"}` | 0.542 |
| `odd_verify_document` | `{"set_id": "d92c5d6b-ff10-4087-36a2-1cfc464cb967", "source_version": "30"}` | 0.91 |
| *initialize* | — | 2.896 |

**Total automated processing time: 5.823 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['dosage and administration', 'recommended dosage', 'deterioration', 'warnings']`
- section codes selected: `['34068-7', '42229-5', '43685-7']`
- index sections matching those keywords: 5
- section_index carries no text: `False`
- sections in index: 47

## Slice returned

- requested codes: `['34068-7', '42229-5', '43685-7']`
- returned codes: `['34068-7', '42229-5', '43685-7']`
- sections returned: 24
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**2.1 Recommended Dosage for Bronchospasm (Acute Episodes or Symptoms Associated with Bronchospasm)** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`
- section_sha256: `6af28a28f34cd3f0ee33013d392f2ce635a023c57cb3dd927deb05d3e2c94a79`
- raw_sha256: `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2`

```text
Adult and pediatric patients aged 4 years and older: 2 inhalations by oral inhalation repeated every 4 to 6 hours; in some patients, 1 inhalation every 4 hours may be sufficient. More frequent administration or a greater number of inhalations is not recommended.
```

**5.2 Deterioration of Asthma** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]/component[2]/section[1]`
- section_sha256: `53775ca0ebcd3cbf341fadc5beca9b299326a753f53cadd0439c4a87c7165f5a`
- raw_sha256: `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2`

```text
Asthma may deteriorate acutely over a period of hours or chronically over several days or longer. If the patient needs more doses of VENTOLIN HFA than usual, this may be a marker of destabilization of asthma and requires reevaluation of the patient and treatment regimen, giving special consideration to the possible need for anti-inflammatory treatment, e.g., corticosteroids.
```

## ODD answer, composed from the slice only

- **2 inhalations every 4 to 6 hours; 1 inhalation every 4 hours may suffice in some patients.**
  - from the slice: `2 inhalations by oral inhalation repeated every 4 to 6 hours; in some patients, 1 inhalation every 4 hours may be sufficient.`
- **More frequent administration or more inhalations is not recommended.**
  - from the slice: `More frequent administration or a greater number of inhalations is not recommended.`
- **Needing more doses than usual may mark destabilization of asthma and requires reevaluation.**
  - from the slice: `If the patient needs more doses of VENTOLIN HFA than usual, this may be a marker of destabilization of asthma and requires reevaluation of the patient and treatment regimen`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`

