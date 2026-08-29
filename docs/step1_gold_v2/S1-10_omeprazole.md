# Gold record S1-10 — omeprazole

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The label's instruction regarding concomitant clopidogrel.

## Identity

| field | value |
| --- | --- |
| set_id | `b6761f84-53ac-4745-a8c8-1e5427d7e179` |
| version | `8` |
| raw SPL path | `data/raw/dailymed/b6761f84-53ac-4745-a8c8-1e5427d7e179/8/label.xml` |
| expected raw SHA-256 | `e0cab1df07d664405d45676c5375d8999f9e8c3ebb084fd620a60b871db96643` |
| recomputed raw SHA-256 | `e0cab1df07d664405d45676c5375d8999f9e8c3ebb084fd620a60b871db96643` |
| digests agree | yes |
| sections in document | 71 |

## Evidence read from the document

### sequence 23 — 5.7 Interaction with Clopidogrel

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]/component[7]/section[1]`

```text
Avoid concomitant use of PRILOSEC with clopidogrel. Clopidogrel is a prodrug. Inhibition of platelet aggregation by clopidogrel is entirely due to an active metabolite. The metabolism of clopidogrel to its active metabolite can be impaired by use with concomitant medications, such as omeprazole, that inhibit CYP2C19 activity. Concomitant use of clopidogrel with 80 mg omeprazole reduces the pharmacological activity of clopidogrel, even when administered 12 hours apart. 

 
When using PRILOSEC, consider alternative anti-platelet therapy [see Drug Interactions (7) and Clinical Pharmacology (12.3)].
```

## Gold answer, and the quote supporting each statement

- **Avoid concomitant use with clopidogrel.**
  - supported by: `Avoid concomitant use of PRILOSEC with clopidogrel.`
- **Consider alternative anti-platelet therapy when using this product.**
  - supported by: `When using PRILOSEC, consider alternative anti-platelet therapy`
- **Concomitant clopidogrel with 80 mg omeprazole reduces clopidogrel activity even 12 hours apart.**
  - supported by: `even when administered 12 hours apart`

## Verdict: SUPPORTED

Section 5.7 states the instruction and the reason for it.
