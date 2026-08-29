# MCP run S1-09 — gabapentin

Produced by running the frozen Step 1 case through the ODD MCP server.
**No gold record was opened, and nothing here is compared or judged.**

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The renal dose-adjustment table by creatinine clearance.
- **Full unedited MCP returns:** `docs/step1_mcp_run/raw/S1-09_gabapentin.json`

## Identity

| field | value |
| --- | --- |
| fixed set_id | `97935fd9-1d4a-43b6-a5d9-de994591187b` |
| fixed version | `48` |
| fixed identity present in find_documents candidates | **yes** |
| candidate_count | 586 |
| selection_performed | False |
| document raw SHA-256 returned by slice | `5772dd19697484b7a98743b09f04cef551bff5caffd1eddd30ef7d89c0a7e9dc` |
| source_version returned | `48` |
| effective_date returned | `2026-05-12` |
| source_url returned | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/97935fd9-1d4a-43b6-a5d9-de994591187b.xml` |

## Tool calls, arguments and timings

| tool | arguments | seconds |
| --- | --- | --- |
| `odd_find_documents` | `{"query": "gabapentin"}` | 1.012 |
| `odd_get_section_index` | `{"set_id": "97935fd9-1d4a-43b6-a5d9-de994591187b", "source_version": "48"}` | 0.849 |
| `odd_get_evidence_slice` | `{"section_codes": ["42229-5"], "set_id": "97935fd9-1d4a-43b6-a5d9-de994591187b", "source_version": "48"}` | 0.734 |
| `odd_verify_document` | `{"set_id": "97935fd9-1d4a-43b6-a5d9-de994591187b", "source_version": "48"}` | 1.132 |
| *initialize* | — | 2.908 |

**Total automated processing time: 6.894 s**

## Section selection

Section codes were chosen from the returned index alone, by matching section titles against keywords taken from the question wording. No gold record informed the choice.

- keywords from the question: `['renal', 'creatinine']`
- section codes selected: `['42229-5']`
- index sections matching those keywords: 3
- section_index carries no text: `False`
- sections in index: 88

## Slice returned

- requested codes: `['42229-5']`
- returned codes: `['42229-5']`
- sections returned: 50
- codes not found: `[]`
- unexpected codes: `[]`
- subsections added implicitly: `False`

### Source text the answer was taken from

**2.3 Dosage Adjustment in Patients with Renal Impairment** — code `42229-5`

- locator: `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]/component[3]/section[1]`
- section_sha256: `302e740c2e80a51383e1a76b245f22e8df268dba139ccfbac80db0225e620c02`
- raw_sha256: `5772dd19697484b7a98743b09f04cef551bff5caffd1eddd30ef7d89c0a7e9dc`

```text
Dosage adjustment in patients 12 years of age and older with renal impairment or undergoing hemodialysis is recommended, as follows (see dosing recommendations above for effective doses in each indication): TABLE 1. NEURONTIN Dosage Based on Renal Function TID = Three times a day; BID = Two times a day; QD = Single daily dose Renal Function Creatinine Clearance (mL/min) Total Daily Dose Range (mg/day) Dose Regimen (mg) ≥ 60 900 to 3600 300 TID 400 TID 600 TID 800 TID 1200 TID >30 to 59 400 to 1400 200 BID 300 BID 400 BID 500 BID 700 BID >15 to 29 200 to 700 200 QD 300 QD 400 QD 500 QD 700 QD 15For patients with creatinine clearance <15 mL/min, reduce daily dose in proportion to creatinine clearance (e.g., patients with a creatinine clearance of 7.5 mL/min should receive one-half the daily dose that patients with a creatinine clearance of 15 mL/min receive). 100 to 300 100 QD 125 QD 150 QD 200 QD 300 QD Post-Hemodialysis Supplemental Dose (mg)Patients on hemodialysis should receive maintenance doses based on estimates of creatinine clearance as indicated in the upper portion of the table and a supplemental post-hemodialysis dose administered after each 4 hours of hemodialysis as indicated in the lower portion of the table. Hemodialysis 125 150 200 250 350 Creatinine clearance (CLCr) is difficult to measure in outpatients. In patients with stable renal function, creatinine clearance can be reasonably well estimated using the equation of Cockcroft and Gault: The use of NEURONTIN in patients less than 12 years of age with compromised renal function has not been studied.
```

## ODD answer, composed from the slice only

- **Dosage adjustment is recommended for patients 12 years and older with renal impairment or on hemodialysis.**
  - from the slice: `Dosage adjustment in patients 12 years of age and older with renal impairment or undergoing hemodialysis is recommended`
- **The table is TABLE 1, keyed on creatinine clearance in mL/min.**
  - from the slice: `TABLE 1. NEURONTIN Dosage Based on Renal Function ... Renal Function Creatinine Clearance (mL/min)`
- **CrCl at or above 60: 900 to 3600 mg/day, dosed TID.**
  - from the slice: `≥ 60 900 to 3600 300 TID 400 TID 600 TID 800 TID 1200 TID`
- **CrCl above 30 to 59: 400 to 1400 mg/day, dosed BID.**
  - from the slice: `>30 to 59 400 to 1400 200 BID 300 BID 400 BID 500 BID 700 BID`
- **CrCl above 15 to 29: 200 to 700 mg/day, dosed QD.**
  - from the slice: `>15 to 29 200 to 700 200 QD 300 QD 400 QD 500 QD 700 QD`

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data write attempts: 0 (data tree identical across the whole run: True)
- execution errors: `[]`
