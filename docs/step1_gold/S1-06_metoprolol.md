# Gold record S1-06 — metoprolol

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** Identify this document's salt, immediate- or extended-release, and dosage form; then give the adult starting dose for hypertension.

## Identity

| field | value |
| --- | --- |
| set_id | `b5f4fed2-369c-4808-a682-8a5b8cfdbb4f` |
| version | `3` |
| raw SPL path | `data/raw/dailymed/b5f4fed2-369c-4808-a682-8a5b8cfdbb4f/3/label.xml` |
| expected raw SHA-256 | `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e` |
| recomputed raw SHA-256 | `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e` |
| digests agree | yes |
| sections in document | 47 |

## Evidence read from the document

### sequence 3 — 1.1 Myocardial Infarction

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[2]/section[1]/component[1]/section[1]`

```text
LOPRESSOR is indicated in the treatment of hemodynamically stable adult patients with myocardial infarction (MI) to reduce cardiovascular mortality.
```

### sequence 5 — 2.1 Myocardial Infarction

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`

```text
The recommended starting dose in hemodynamically stable patients is 50 mg orally every 6 hours. In case of intolerance, reduce the starting dose to 25 mg orally every 6 hours and administer for 48 hours. Titrate dosage based on tolerability and hemodynamic parameters (i.e., heart rate, blood pressure). LOPRESSOR should preferably be administered with or following meals. The maximum daily maintenance dosage is 100 mg orally twice daily.
```

### sequence 6 — 3 DOSAGE FORMS AND STRENGTHS

- **section code:** `43678-2` (DOSAGE FORMS & STRENGTHS SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]`

```text
LOPRESSOR is supplied as a 12.5 mg tablet that is pink-colored, film coated, round, biconvex, debossed with “˄E” on one side, and plain on the other side.
```

## Gold answer, and the quote supporting each statement

- **Salt: metoprolol tartrate.**
  - supported by: `DOCUMENT TITLE: LOPRESSOR ®(metoprolol tartrate) tablets, for oral use`
- **Dosage form: film-coated tablet, 12.5 mg.**
  - supported by: `LOPRESSOR is supplied as a 12.5 mg tablet that is pink-colored, film coated`
- **Release characteristic: the document does not state one for this product.**
  - supported by: `ABSENT: 'extended-release' appears 0 times; 'immediate-release' appears only in 12.3 Pharmacokinetics and the CYP2D6 interaction discussion, describing immediate-release metoprolol generally, not this product's dosage form.`
- **Adult starting dose for hypertension: not stated anywhere in this document.**
  - supported by: `ABSENT: the sole indication is 1.1 Myocardial Infarction and the sole adult dosing is 2.1 Myocardial Infarction. 'hypertension' occurs twice, both describing clonidine rebound hypertension in drug interactions, never as an indication.`

## Verdict: VALID_UNKNOWN

The salt and dosage form are stated and were read out of the document. The adult hypertension starting dose is genuinely absent: this is a myocardial-infarction-only label. The question as asked cannot be answered from this pinned document, so the case is VALID_UNKNOWN and does not count toward the pass total. This is a property of the caller-supplied identity, not of ODD.
