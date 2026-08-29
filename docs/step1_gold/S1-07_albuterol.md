# Gold record S1-07 — albuterol

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The dosing interval, the maximum frequency of use, and the label's warning when more frequent use than usual becomes necessary.

## Identity

| field | value |
| --- | --- |
| set_id | `d92c5d6b-ff10-4087-36a2-1cfc464cb967` |
| version | `30` |
| raw SPL path | `data/raw/dailymed/d92c5d6b-ff10-4087-36a2-1cfc464cb967/30/label.xml` |
| expected raw SHA-256 | `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2` |
| recomputed raw SHA-256 | `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2` |
| digests agree | yes |
| sections in document | 47 |

## Evidence read from the document

### sequence 6 — 2.1 Recommended Dosage for Bronchospasm (Acute Episodes or Symptoms Associated with Bronchospasm)

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[3]/section[1]/component[1]/section[1]`

```text
Adult and pediatric patients aged 4 years and older: 2 inhalations by oral inhalation repeated every 4 to 6 hours; in some patients, 1 inhalation every 4 hours may be sufficient. More frequent administration or a greater number of inhalations is not recommended.
```

### sequence 13 — 5.2 Deterioration of Asthma

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[6]/section[1]/component[2]/section[1]`

```text
Asthma may deteriorate acutely over a period of hours or chronically over several days or longer. If the patient needs more doses of VENTOLIN HFA than usual, this may be a marker of destabilization of asthma and requires reevaluation of the patient and treatment regimen, giving special consideration to the possible need for anti-inflammatory treatment, e.g., corticosteroids.
```

## Gold answer, and the quote supporting each statement

- **2 inhalations every 4 to 6 hours; in some patients 1 inhalation every 4 hours may suffice.**
  - supported by: `2 inhalations by oral inhalation repeated every 4 to 6 hours; in some patients, 1 inhalation every 4 hours may be sufficient`
- **More frequent administration or more inhalations is not recommended.**
  - supported by: `More frequent administration or a greater number of inhalations is not recommended.`
- **Needing more doses than usual may mark destabilization of asthma and requires reevaluation.**
  - supported by: `If the patient needs more doses of VENTOLIN HFA than usual, this may be a marker of destabilization of asthma and requires reevaluation`

## Verdict: SUPPORTED

Dosing interval and maximum frequency are in 2.1; the warning on more frequent need is in 5.2.
