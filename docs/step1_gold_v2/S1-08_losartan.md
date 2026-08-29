# Gold record S1-08 — losartan

Read from the preserved bytes **before ODD was run**, with the standard library
only. No ODD module, no network. No case has been executed against ODD.

- **Protocol:** `docs/STEP1_MANUAL_VALIDATION_V1.md` (`c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`)
- **Question:** The adult starting dose and maximum dose for hypertension, and the starting dose in patients with intravascular volume depletion.

## Identity

| field | value |
| --- | --- |
| set_id | `9949448f-c3b9-44ee-94ed-c1aca8c90f39` |
| version | `9` |
| raw SPL path | `data/raw/dailymed/9949448f-c3b9-44ee-94ed-c1aca8c90f39/9/label.xml` |
| expected raw SHA-256 | `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f` |
| recomputed raw SHA-256 | `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f` |
| digests agree | yes |
| sections in document | 78 |

## Evidence read from the document

### sequence 9 — (section states no title)

- **section code:** `42229-5` (SPL UNCLASSIFIED SECTION)
- **position:** `/document[1]/component[1]/structuredBody[1]/component[4]/section[1]/component[1]/section[1]/component[1]/section[1]`

```text
Adult Hypertension
 

 
The usual starting dose of COZAAR is 50 mg once daily. The dosage can be increased to a maximum dose of 100 mg once daily as needed to control blood pressure [see Clinical Studies (14.1)]. A starting dose of 25 mg is recommended for patients with possible intravascular depletion (e.g., on diuretic therapy).
```

## Gold answer, and the quote supporting each statement

- **Usual starting dose 50 mg once daily.**
  - supported by: `The usual starting dose of COZAAR is 50 mg once daily.`
- **Maximum dose 100 mg once daily.**
  - supported by: `increased to a maximum dose of 100 mg once daily`
- **Starting dose 25 mg where intravascular depletion is possible.**
  - supported by: `A starting dose of 25 mg is recommended for patients with possible intravascular depletion`

## Verdict: SUPPORTED

One untitled subsection under 2.1 Hypertension states all three figures.

**Note on this document:** This section element carries no <title> child; 'Adult Hypertension' is the first line of its text.
