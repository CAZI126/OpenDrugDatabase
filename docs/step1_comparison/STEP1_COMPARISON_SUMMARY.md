# Step 1 comparison — provisional

Gold records and MCP outputs, both frozen before this comparison, judged case by case against the frozen protocol. **This is provisional. No final pass is declared here.**

- protocol `c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`
- gold fingerprint `3764fd95a8eb38d3a4f7d2b4fc50feaaaf9b604d93e89f0bcdb1f9712bd16151`
- MCP output fingerprint `8c4dd4f6685bf61590cd97a0cd16a6c24676fa3523869fa257803dfe22f38a45`
- comparison fingerprint `e31b6742295ed882150e010c45b7143330f0ceec288ec8d6ed58e73b957be311`

## Result

| | count |
| --- | --- |
| PASS | **8** |
| FAIL | 1 |
| VALID_UNKNOWN (not counted toward PASS) | 1 |

**PROVISIONAL_STEP1_PASS** — the frozen threshold is 8 of 10.

## Cases

| case | drug | gold | provisional | find (s) | total (s) | verify |
| --- | --- | --- | --- | --- | --- | --- |
| S1-01 | atorvastatin | SUPPORTED | **PASS** | 1.092 | 12.317 | VERIFIED |
| S1-02 | metformin | SUPPORTED | **FAIL** | 0.959 | 6.914 | VERIFIED |
| S1-03 | levothyroxine | SUPPORTED | **PASS** | 0.953 | 6.693 | VERIFIED |
| S1-04 | lisinopril | SUPPORTED | **PASS** | 0.802 | 6.127 | VERIFIED |
| S1-05 | amlodipine | SUPPORTED | **PASS** | 0.768 | 5.954 | VERIFIED |
| S1-06 | metoprolol | VALID_UNKNOWN | **VALID_UNKNOWN** | 0.875 | 5.683 | VERIFIED |
| S1-07 | albuterol | SUPPORTED | **PASS** | 0.731 | 5.823 | VERIFIED |
| S1-08 | losartan | SUPPORTED | **PASS** | 0.715 | 5.999 | VERIFIED |
| S1-09 | gabapentin | SUPPORTED | **PASS** | 1.012 | 6.894 | VERIFIED |
| S1-10 | omeprazole | SUPPORTED | **PASS** | 0.723 | 7.802 | VERIFIED |

## The one failure

**S1-02 metformin.** The document states all four eGFR criteria in section 2.3, so the gold is SUPPORTED. ODD could not deliver them: the section index reports that section with `section_code: UNKNOWN`, because the section element in this SPL carries no `<code>` child, and asking the slice for the code `UNKNOWN` returns `section_codes_not_found: ["UNKNOWN"]` with no text. Only the contraindication section was retrievable, which carries the below-30 threshold and none of the others.

Four of five gold claims are therefore unanswered. Under the frozen protocol this is 'required text is missing' and is FAIL. It is not VALID_UNKNOWN: the document does state the answer, and what failed was the retrieval, not the source.

## The one valid unknown

**S1-06 metoprolol.** The pinned identity is a myocardial-infarction-only Lopressor label with no hypertension indication and no hypertension dosing anywhere in it. ODD returned the salt and the dosage form, and stopped at UNKNOWN for the release characteristic and the hypertension dose rather than supplying either from outside the document. That is the required behaviour, and under the frozen protocol it does not count toward the pass total.

## Reading this honestly

Eight passes against a threshold of eight is the narrowest possible margin. One case carries no slack at all: had S1-06's identity been a label that did state a hypertension dose, or had any single passing case missed a claim, the result would be below the line. The margin is a fact about this result and should be read as one.

The independence of this run is also limited, and the limit is recorded rather than glossed: the gold records were written in the same session that ran the cases, so the gold content was already known when the run was driven. Section selection was made mechanically from question keywords and the returned index to reduce that influence, but this is not a blind run, and a human check of the evidence is what settles it.
