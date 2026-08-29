# Gold record S1-02 — metformin

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Starting, continuation, and discontinuation criteria based on eGFR.

## Identity

| field | value |
| --- | --- |
| set_id | `c82a10fa-1e8e-46b6-890a-737de3f34ee1` |
| version | `17` |
| raw SPL path | `data/raw/dailymed/c82a10fa-1e8e-46b6-890a-737de3f34ee1/17/label.xml` |
| expected raw SHA-256 | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| recomputed raw SHA-256 | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| digests agree | yes |
| sections in document | 45 |

## Evidence read from the document

### sequence 8 — 2.3 Recommendations for Use in Renal Impairment

- **section code:** (section states no code)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[3]/section[1]`

```text
Assess renal function prior to initiation of metformin hydrochloride tablets and periodically thereafter.

 
Metformin hydrochloride tablets are contraindicated in patients with an estimated glomerular filtration rate (eGFR) below 30 mL/minute/1.73 m2.

 
Initiation of metformin hydrochloride tablets in patients with an eGFR between 30 mL/minute/1.73 m2to 45 mL/minute/1.73 m2is not recommended.

 
In patients taking metformin hydrochloride tablets whose eGFR later falls below 45 mL/min/1.73 m2, assess the benefit risk of continuing therapy.

 
Discontinue metformin hydrochloride tablets if the patient's eGFR later falls below 30 mL/minute/1.73 m2
 [
 s
 ee Warnings and Precautions (5.1)].
```

### sequence 11 — 4 CONTRAINDICATIONS

- **section code:** `34070-3` (CONTRAINDICATIONS SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[7]/section[1]`

```text
Metformin hydrochloride tablets are contraindicated in patients with:

 

 
Severe renal impairment (eGFR below 30 mL/min/1.73 m2) [see Warnings and Precautions (5.1)].

 
Hypersensitivity to metformin.

 
Acute or chronic metabolic acidosis, including diabetic ketoacidosis, with or without coma.
```

## Gold answer, and the quote supporting each statement

- **Contraindicated below eGFR 30 mL/minute/1.73 m2.**
  - supported by: `contraindicated in patients with an estimated glomerular filtration rate (eGFR) below 30`
- **Initiation is not recommended at eGFR 30 to 45 mL/minute/1.73 m2.**
  - supported by: `Initiation of metformin hydrochloride tablets in patients with an eGFR between 30`
- **If eGFR later falls below 45, assess the benefit risk of continuing.**
  - supported by: `whose eGFR later falls below 45 mL/min/1.73 m2, assess the benefit risk of continuing therapy`
- **Discontinue if eGFR later falls below 30.**
  - supported by: `Discontinue metformin hydrochloride tablets if the patient's eGFR later falls below 30`
- **Assess renal function before initiation and periodically thereafter.**
  - supported by: `Assess renal function prior to initiation`

## Verdict: SUPPORTED

Section 2.3 states all four eGFR thresholds; the contraindications section corroborates the below-30 threshold.

**Note on this document:** The 2.3 section element carries no <code> child in this document. Recorded as stated, not filled in.
