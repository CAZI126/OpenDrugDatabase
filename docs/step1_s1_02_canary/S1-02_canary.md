# S1-02 canary — metformin, sections named by position

One run of the fixed identity through the ODD MCP server, from preserved bytes only.
The two sections were named by the position the index reported for them.

**No AI summary was written.** What is frozen below is the primary-source text the
slice returned, as returned. That text is the material to be judged.

## Identity

| field | value |
| --- | --- |
| set_id | `c82a10fa-1e8e-46b6-890a-737de3f34ee1` |
| version | `17` |
| fixed raw SHA-256 | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| raw SHA-256 returned | `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d` |
| digests agree | yes |
| source_url | `https://dailymed.nlm.nih.gov/dailymed/services/v2/spls/c82a10fa-1e8e-46b6-890a-737de3f34ee1.xml` |

## Sections chosen from the index

| section_title | section_code | evidence_locator |
| --- | --- | --- |
| 2.3 Recommendations for Use in Renal Impairment | `UNKNOWN` | `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[3]/section[1]` |
| 2.4 Discontinuation for Iodinated Contrast Imaging Procedures | `UNKNOWN` | `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[4]/section[1]` |

- requested positions: 2
- positions not found: `[]`
- returned sections: 2
- unexpected section codes: `[]`
- subsections added implicitly: `False`

## The primary-source text the slice returned

### 2.3 Recommendations for Use in Renal Impairment

- section code: `UNKNOWN`
- position: `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[3]/section[1]`
- section_sha256: `914a57b4e566813c2c1c9ee6ab25fa795ec443413795b014a10a8783d17a320e`
- raw_sha256: `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d`

```text
Assess renal function prior to initiation of metformin hydrochloride tablets and periodically thereafter. Metformin hydrochloride tablets are contraindicated in patients with an estimated glomerular filtration rate (eGFR) below 30 mL/minute/1.73 m2. Initiation of metformin hydrochloride tablets in patients with an eGFR between 30 mL/minute/1.73 m2to 45 mL/minute/1.73 m2is not recommended. In patients taking metformin hydrochloride tablets whose eGFR later falls below 45 mL/min/1.73 m2, assess the benefit risk of continuing therapy. Discontinue metformin hydrochloride tablets if the patient's eGFR later falls below 30 mL/minute/1.73 m2 [ s ee Warnings and Precautions (5.1)].
```

### 2.4 Discontinuation for Iodinated Contrast Imaging Procedures

- section code: `UNKNOWN`
- position: `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[4]/section[1]`
- section_sha256: `996939d67a070ac2bf3d6fb3fbd895ea060da066871c72ce68237bdd481b04b5`
- raw_sha256: `9adfa16cd77cad975fa8ee0d95ddc505f32d4d023a8c8e8c80d6a272b7c2a52d`

```text
Discontinue metformin hydrochloride tablets at the time of, or prior to, an iodinated contrast imaging procedure in patients with an eGFR between 30 mL/min/1.73 m2 and 60 mL/min/1.73 m2; in patients with a history of liver disease, alcoholism, or heart failure; or in patients who will be administered intra- arterial iodinated contrast. Re-evaluate eGFR 48 hours after the imaging procedure; restart metformin hydrochloride tablets if renal function is stable.
```

## Verification

- result: `VERIFIED`
- raw bytes SHA-256: `VERIFIED`
- section anchors: `VERIFIED`
- failure reasons: `[]`

## Run conditions

- network attempts: 0
- data writes: 0 (data tree identical: True, 23417 files either side)
- total automated time: 10.418 s
