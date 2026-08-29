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
