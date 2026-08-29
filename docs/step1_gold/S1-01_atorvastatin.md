# Gold record S1-01 — atorvastatin

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and the dose range.

## Identity

| field | value |
| --- | --- |
| set_id | `a60cc18b-0631-4cf0-b021-9f52224ece65` |
| version | `8` |
| raw SPL path | `data/raw/dailymed/a60cc18b-0631-4cf0-b021-9f52224ece65/8/label.xml` |
| expected raw SHA-256 | `c6748f079a3cf15a3d9fe19dde9012fb62746cd68ea8e21506daab8d6f2a32fd` |
| recomputed raw SHA-256 | `c6748f079a3cf15a3d9fe19dde9012fb62746cd68ea8e21506daab8d6f2a32fd` |
| digests agree | yes |
| sections in document | 68 |

## Evidence read from the document

### sequence 5 — 2.2 Recommended Dosage in Adult Patients

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[2]/section[1]`

```text
The recommended starting dosage of LIPITOR is 10 mg to 20 mg once daily. The dosage range is 10 mg to 80 mg once daily. Patients who require reduction in LDL-C greater than 45% may be started at 40 mg once daily.
```

## Gold answer, and the quote supporting each statement

- **Starting dosage: 10 mg to 20 mg once daily.**
  - supported by: `The recommended starting dosage of LIPITOR is 10 mg to 20 mg once daily.`
- **Dosage range: 10 mg to 80 mg once daily.**
  - supported by: `The dosage range is 10 mg to 80 mg once daily.`
- **Patients requiring greater than 45% LDL-C reduction may start at 40 mg once daily.**
  - supported by: `Patients who require reduction in LDL-C greater than 45% may be started at 40 mg once daily.`

## Verdict: SUPPORTED

One section states the starting dosage, the range, and the 40 mg starting option, in the document's own words.
