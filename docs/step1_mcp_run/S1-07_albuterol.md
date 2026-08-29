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
