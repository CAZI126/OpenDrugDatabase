# Step 1 — manual validation protocol, v1

This protocol is **frozen before any result exists**. It is written so that the
answer to "is ODD actually useful?" is decided by evidence gathered afterwards,
not by criteria adjusted once the evidence is in.

Nothing in this document may be changed after the first case is run. If it turns
out to be the wrong protocol, that is a finding to report — not an edit to make.

- **Status:** frozen, awaiting execution
- **Version:** STEP1-MANUAL-VALIDATION/1.0.0
- **Execution:** not started. No case in this document has been run.

---

## 1. What is being judged

Whether ODD, as it stands today, can carry a clinician-style question to the
preserved primary source and return the passage that answers it — with the
provenance intact and nothing invented.

This is a test of **transport and provenance**, not of medicine. ODD is not being
asked whether an answer is clinically correct, and no case here is scored on
clinical judgement. The question in each case exists only to force ODD to locate
a specific passage in a specific document.

## 2. What is fixed

### 2.1 The ten identities

Taken from `docs/examples/top10_caller_supplied_identities.json`
(`schema_version: odd-core-batch-manifest/1.0.0`, `identity_source: caller_supplied`).
These are the caller's own rows. ODD did not choose, rank, score, or endorse
them, and their presence here is not a claim that they are the right label for
the named drug. Each is pinned by set id, version, and the SHA-256 of its
preserved bytes, so "the document" cannot drift during the run.

| # | drug (caller's label) | set_id | version | raw SHA-256 |
| --- | --- | --- | --- | --- |
| 1 | atorvastatin | `a60cc18b-0631-4cf0-b021-9f52224ece65` | 8 | `c6748f079a3cf15a3d9fe19dde9012fb62746cd68ea8e21506daab8d6f2a32fd` |
| 2 | metformin | `c82a10fa-1e8e-46b6-890a-737de3f34ee1` | 17 | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| 3 | levothyroxine | `1e11ad30-1041-4520-10b0-8f9d30d30fcc` | 1537 | `de366bdd1a38c827eff6c082896ea88f8ffde929b647df38421f595d9437203a` |
| 4 | lisinopril | `838c2d78-d2d8-4981-9ec9-e50ef9e1a5d8` | 2 | `2e2b2246fbd5a0183f6559cdab91359616333318b650efa8941ede54827aa5aa` |
| 5 | amlodipine | `7367289c-b0b0-466a-83e2-558e2985c29f` | 10 | `2411f602c5819fb1c572b9a1fa5972476a3c242c046d46624995995cac3e7c51` |
| 6 | metoprolol | `b5f4fed2-369c-4808-a682-8a5b8cfdbb4f` | 3 | `7ee92b8303bf037f308f90f0d2c4bae1432af6d52331d793c762af84e507354e` |
| 7 | albuterol | `d92c5d6b-ff10-4087-36a2-1cfc464cb967` | 30 | `ea2e5e579f6fa81deb19c3561b5924f5e8ebaa830224f47403605c02b51278b2` |
| 8 | losartan | `9949448f-c3b9-44ee-94ed-c1aca8c90f39` | 9 | `855caab1c9ba60a0a4b127d58f2f70ce4af4de37f13ef25f01bfb4dcc193178f` |
| 9 | gabapentin | `97935fd9-1d4a-43b6-a5d9-de994591187b` | 48 | `5772dd19697484b7a98743b09f04cef551bff5caffd1eddd30ef7d89c0a7e9dc` |
| 10 | omeprazole | `b6761f84-53ac-4745-a8c8-1e5427d7e179` | 8 | `e0cab1df07d664405d45676c5375d8999f9e8c3ebb084fd620a60b871db96643` |

Every one is preserved under `data/raw/dailymed/<set_id>/<version>/label.xml`,
verified present at freeze time. Source URL for each is
`https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/<set_id>.xml`.

### 2.2 The ten questions

| Case | Drug | Question |
| --- | --- | --- |
| S1-01 | atorvastatin | The adult starting dose and the dose range. |
| S1-02 | metformin | Starting, continuation, and discontinuation criteria based on eGFR. |
| S1-03 | levothyroxine | Timing relative to breakfast, and the dosing interval from drugs that affect its absorption. |
| S1-04 | lisinopril | The contraindication on concomitant use with sacubitril/valsartan, and the washout interval required. |
| S1-05 | amlodipine | The adult starting dose and maximum dose for hypertension. |
| S1-06 | metoprolol | Identify this document's salt, immediate- or extended-release, and dosage form; then give the adult starting dose for hypertension. |
| S1-07 | albuterol | The dosing interval, the maximum frequency of use, and the label's warning when more frequent use than usual becomes necessary. |
| S1-08 | losartan | The adult starting dose and maximum dose for hypertension, and the starting dose in patients with intravascular volume depletion. |
| S1-09 | gabapentin | The renal dose-adjustment table by creatinine clearance. |
| S1-10 | omeprazole | The label's instruction regarding concomitant clopidogrel. |

The question is answered **from the fixed document only**. What some other label
for the same drug says is irrelevant to the case, and so is any outside clinical
knowledge.

## 3. Gold record — built before ODD is run

For each case, in this order, and never the other way round:

1. Open the pinned `label.xml` directly, independently of ODD.
2. Read the answer to the question out of that file.
3. Record: the answering passage verbatim, its section code, its section title,
   and its position in the document.
4. Freeze that gold record.
5. **Only then** run ODD for that case.

A gold record written or amended after seeing ODD's output is not a gold record.
If the gold turns out to be wrong, the case is reported with both the original
gold and the correction, and the correction does not retroactively rescue a FAIL.

If the pinned document genuinely does not state an answer, the gold record says
so explicitly. That is the only route to VALID_UNKNOWN (§6).

## 4. Execution — per case

From a **new stdio process** running the registered ODD MCP server, in order:

1. `odd_find_documents` — search for the document.
2. Identify the fixed identity among the candidates. **The human selects it.**
   ODD must not choose, and a run in which ODD narrows to one is a finding.
3. `odd_get_section_index` — obtain the index.
4. `odd_get_evidence_slice` — obtain only the sections needed for the question.
5. `odd_verify_document` — verify.
6. Record what ODD returned: passage text, source, version, section code,
   evidence locator, raw SHA-256.
7. Open the preserved primary source independently of that output.
8. Place the two side by side so a human can compare them line by line.

## 5. PASS conditions

A case is PASS only when **every** one of these holds:

- `odd_find_documents` returns the fixed identity among its candidates within
  **5 seconds**.
- The returned information is sufficient for a human to select the fixed identity.
- The section index contains the section that carries the answer.
- The slice returns the primary-source text the question needs, with nothing
  required missing.
- Source, set_id, version, section code, and evidence position are all correct.
- `odd_verify_document` succeeds.
- Every piece of drug information in ODD's answer is directly supported by the
  retrieved primary source.
- No supplement, inference, or medical adjudication beyond the source text.
- Automated processing time for the case is within **15 seconds**.
- The preserved sources and the data tree are unchanged.
- Network attempts: **0**.

### Immediate FAIL

- The fixed identity does not appear in the search results.
- A different document is treated as the answer.
- Required text is missing.
- An assertion not present in the source.
- Wrong provenance or wrong position.
- Verification fails.
- Timeout.
- Any data change during the run.

Judgement is **per case and independent**. The ten are not assessed as a group,
and no case is upgraded because the others went well.

## 6. VALID_UNKNOWN

Permitted **only** when the pinned document's own text genuinely contains no
answer to the question, as established by the gold record written before ODD ran.

Not permitted for: a search miss, an extraction failure, an implementation
defect, or a timeout. Those are FAIL.

**VALID_UNKNOWN does not count toward the PASS total.** A case that cannot be
answered because the document says nothing is honest, but it is not evidence that
ODD works — so it is recorded separately and counted separately.

## 7. Overall result

| Condition | Result |
| --- | --- |
| PASS ≥ 8 of 10 | `STEP1_PASS` |
| PASS ≤ 7 of 10 | `STEP1_FAIL` |
| Before a human has reviewed all ten | `AWAITING_HUMAN_SIGNOFF` |

No automated run may declare a final pass. The evidence for all ten cases is
presented so a human can check each one, and the result stands only after that.

There is no production success counter in ODD, and this protocol does not create
one. The PASS / FAIL / VALID_UNKNOWN counts in the validation report are the only
figures used.

## 8. Per-case record

Each case is reported with exactly these fields:

```text
Case ID
Drug / subject
Question
Document ODD selected
set_id / version
Evidence section code
Text ODD returned
Corresponding passage in the preserved source
Text match
Position match
SHA / verify
ODD's answer
Conclusion readable from the source
PASS / FAIL / VALID_UNKNOWN
Reason for the judgement
Elapsed time
```

## 9. Out of scope

Not part of Step 1, and not to be started because of anything Step 1 finds:
remote MCP, phone delivery, further title handling, `find_documents`
optimisation, changes to ODD, its tests, the catalog, or the data tree, new
candidate-selection rules, drug-specific branches, medical adjudication, and any
change to these ten questions or these criteria.

A mock or fixture success is never counted as a production success.

## 10. State at freeze time

```text
protocol version   STEP1-MANUAL-VALIDATION/1.0.0
main               9c2080882d6758df2d70743cbec0d53ec8255dd2
preserved documents 3,872
catalog             record_count 3,872 / indexed 3,872 / unindexed 0
catalog sha256      0077cd7a45ef105a099597c8b7bea02ba1853b28361d9ddf9e036610642fa340
source fingerprint  5fbb9c57f015487c0b7314cb551c2a719669cabba3581c649e38aee832704006
data tree           23,417 files
data tree digest    643cbb284c8caf6d60e70c6d698968fad22cb70085e2000ea1b3b69279e6bb2a
cases executed      0
```
