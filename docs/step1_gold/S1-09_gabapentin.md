# Gold record S1-09 — gabapentin

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The renal dose-adjustment table by creatinine clearance.

## Identity

| field | value |
| --- | --- |
| set_id | `97935fd9-1d4a-43b6-a5d9-de994591187b` |
| version | `48` |
| raw SPL path | `data/raw/dailymed/97935fd9-1d4a-43b6-a5d9-de994591187b/48/label.xml` |
| expected raw SHA-256 | `5772dd19697484b7a98743b09f04cef551bff5caffd1eddd30ef7d89c0a7e9dc` |
| recomputed raw SHA-256 | `5772dd19697484b7a98743b09f04cef551bff5caffd1eddd30ef7d89c0a7e9dc` |
| digests agree | yes |
| sections in document | 88 |

## Evidence read from the document

### sequence 9 — 2.3 Dosage Adjustment in Patients with Renal Impairment

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]/component[3]/section[1]`

```text
Dosage adjustment in patients 12 years of age and older with renal impairment or undergoing hemodialysis is recommended, as follows (see dosing recommendations above for effective doses in each indication):

 

 
TABLE 1. NEURONTIN Dosage Based on Renal Function

 
 
 
 
 
 
 
 
 

 
TID = Three times a day; BID = Two times a day; QD = Single daily dose

 

 
 
 

 

 
Renal Function Creatinine Clearance (mL/min)

 

 

 
Total Daily Dose Range

 
(mg/day)

 

 

 
Dose Regimen

 
(mg)

 

 

 

 

 
≥ 60

 

 

 
900 to 3600

 

 

 
300 TID

 

 

 
400 TID

 

 

 
600 TID

 

 

 
800 TID

 

 

 
1200 TID

 

 

 

 

 
>30 to 59

 

 

 
400 to 1400

 

 

 
200 BID

 

 

 
300 BID

 

 

 
400 BID

 

 

 
500 BID

 

 

 
700 BID

 

 

 

 

 
>15 to 29

 

 

 
200 to 700

 

 

 
200 QD

 

 

 
300 QD

 

 

 
400 QD

 

 

 
500 QD

 

 

 
700 QD

 

 

 

 

 
15For patients with creatinine clearance <15 mL/min, reduce daily dose in proportion to creatinine clearance (e.g., patients with a creatinine clearance of 7.5 mL/min should receive one-half the daily dose that patients with a creatinine clearance of 15 mL/min receive).
 

 

 

 
100 to 300

 

 

 
100 QD

 

 

 
125 QD

 

 

 
150 QD

 

 

 
200 QD

 

 

 
300 QD

 

 

 

 

 

 

 

 

 

 

 

 
Post-Hemodialysis Supplemental Dose (mg)Patients on hemodialysis should receive maintenance doses based on estimates of creatinine clearance as indicated in the upper portion of the table and a supplemental post-hemodialysis dose administered after each 4 hours of hemodialysis as indicated in the lower portion of the table.
 

 

 

 

 

 

 

 

 

 

 
Hemodialysis

 

 

 

 
125
 

 

 

 
150
 

 

 

 
200
 

 

 

 
250
 

 

 

 
350
 

 

 

 
 

 
 

 
Creatinine clearance (CLCr) is difficult to measure in outpatients. In patients with stable renal function, creatinine clearance can be reasonably well estimated using the equation of Cockcroft and Gault:

 
 
The use of NEURONTIN in patients less than 12 years of age with compromised renal function has not been studied.
```

## Gold answer, and the quote supporting each statement

- **Dosage adjustment is recommended for patients 12 years and older with renal impairment or on hemodialysis.**
  - supported by: `Dosage adjustment in patients 12 years of age and older with renal impairment or undergoing hemodialysis is recommended`
- **The table is titled TABLE 1 and is keyed on creatinine clearance in mL/min.**
  - supported by: `TABLE 1. NEURONTIN Dosage Based on Renal Function`
- **CrCl at or above 60: total daily dose 900 to 3600 mg, given 300/400/600/800/1200 mg TID.**
  - supported by: `900 to 3600`
- **CrCl above 30 to 59: total daily dose 400 to 1400 mg, given BID.**
  - supported by: `400 to 1400`

## Verdict: SUPPORTED

Section 2.3 carries TABLE 1 with creatinine-clearance bands, total daily dose ranges, and regimens.

**Note on this document:** The table is XML table markup; the extracted text preserves the cell values in document order, one per line.
