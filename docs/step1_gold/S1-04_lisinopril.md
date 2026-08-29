# Gold record S1-04 — lisinopril

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The contraindication on concomitant use with sacubitril/valsartan, and the washout interval required.

## Identity

| field | value |
| --- | --- |
| set_id | `838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8` |
| version | `2` |
| raw SPL path | `data/raw/dailymed/838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8/2/label.xml` |
| expected raw SHA-256 | `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa` |
| recomputed raw SHA-256 | `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa` |
| digests agree | yes |
| sections in document | 61 |

## Evidence read from the document

### sequence 14 — 4 CONTRAINDICATIONS

- **section code:** `34070-3` (CONTRAINDICATIONS SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]`

```text
Zestril is contraindicated in combination with a neprilysin inhibitor (e.g., sacubitril). Do not administer Zestril within 36 hours of switching to or from sacubitril/valsartan, a neprilysin inhibitor [
 see Warnings and Precautions (5.2)].

 
Zestril is contraindicated in patients with:

 

 
a history of angioedema or hypersensitivity related to previous treatment with an angiotensin converting enzyme inhibitor

 
hereditary or idiopathic angioedema

 

 
Do not co-administer aliskiren with ZESTRIL in patients with diabetes [see
 
 Drug Interactions (7.4)
 
 ].
```

## Gold answer, and the quote supporting each statement

- **Contraindicated in combination with a neprilysin inhibitor such as sacubitril.**
  - supported by: `contraindicated in combination with a neprilysin inhibitor (e.g., sacubitril)`
- **Do not administer within 36 hours of switching to or from sacubitril/valsartan.**
  - supported by: `Do not administer Zestril within 36 hours of switching to or from sacubitril/valsartan`

## Verdict: SUPPORTED

The contraindications section states both the contraindication and the 36-hour interval.
