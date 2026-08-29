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

---

## V2 addition — completeness audit

The completeness audit found that the V1 gold did not carry section 2.4, which the question also reaches: it states what to do about iodinated contrast imaging at an eGFR between 30 and 60, and the re-evaluation and restart that follow. The V1 record and the V1 verdict are unchanged; this addition applies to the next run only.

### 2.4 Discontinuation for Iodinated Contrast Imaging Procedures

- **section code:** (this section element states no `<code>`)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[4]/section[1]`

```text
Discontinue metformin hydrochloride tablets at the time of, or prior to, an iodinated contrast imaging procedure in patients with an eGFR between 30 mL/min/1.73 m2 and 60 mL/min/1.73 m2; in patients with a history of liver disease, alcoholism, or heart failure; or in patients who will be administered intra- arterial iodinated contrast. Re-evaluate eGFR 48 hours after the imaging procedure; restart metformin hydrochloride tablets if renal function is stable.
```

### Added gold claims, and the quote supporting each

- **At an eGFR between 30 and 60 mL/min/1.73 m2, discontinue at the time of, or prior to, an iodinated contrast imaging procedure.**
  - supported by: `Discontinue metformin hydrochloride tablets at the time of, or prior to, an iodinated contrast imaging procedure in patients with an eGFR between 30 mL/min/1.73 m2 and 60 mL/min/1.73 m2`
- **Re-evaluate eGFR 48 hours after the imaging procedure.**
  - supported by: `Re-evaluate eGFR 48 hours after the imaging procedure;`
- **Restart if renal function is stable.**
  - supported by: `restart metformin hydrochloride tablets if renal function is stable.`

The V1 claims for this case stand unchanged. With these three added, the gold answer for S1-02 covers the eGFR criteria in section 2.3 and the contrast-imaging criteria in section 2.4.
