# Gold record S1-05 — amlodipine

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and maximum dose for hypertension.

## Identity

| field | value |
| --- | --- |
| set_id | `7367289c-b0b0-466a-83e2-558e2985c29f` |
| version | `10` |
| raw SPL path | `data/raw/dailymed/7367289c-b0b0-466a-83e2-558e2985c29f/10/label.xml` |
| expected raw SHA-256 | `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51` |
| recomputed raw SHA-256 | `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51` |
| digests agree | yes |
| sections in document | 65 |

## Evidence read from the document

### sequence 9 — 2.1 Adults

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`

```text
The usual initial antihypertensive oral dose of NORVASC is 5 mg once daily, and the maximum dose is 10 mg once daily. 

 
Small, fragile, or elderly patients, or patients with hepatic insufficiency may be started on 2.5 mg once daily and this dose may be used when adding NORVASC to other antihypertensive therapy.

 
Adjust dosage according to blood pressure goals. In general, wait 7 to 14 days between titration steps. Titrate more rapidly, however, if clinically warranted, provided the patient is assessed frequently.

 

 Angina: The recommended dose for chronic stable or vasospastic angina is 5–10 mg, with the lower dose suggested in the elderly and in patients with hepatic insufficiency. Most patients will require 10 mg for adequate effect.

 

 Coronary artery disease: The recommended dose range for patients with coronary artery disease is 5–10 mg once daily. In clinical studies, the majority of patients required 10 mg [see Clinical Studies (14.4)].
```

## Gold answer, and the quote supporting each statement

- **Usual initial antihypertensive oral dose 5 mg once daily.**
  - supported by: `The usual initial antihypertensive oral dose of NORVASC is 5 mg once daily`
- **Maximum dose 10 mg once daily.**
  - supported by: `the maximum dose is 10 mg once daily`
- **Small, fragile, elderly, or hepatic-insufficiency patients may start at 2.5 mg once daily.**
  - supported by: `may be started on 2.5 mg once daily`

## Verdict: SUPPORTED

Section 2.1 Adults states the initial and maximum antihypertensive doses directly.
