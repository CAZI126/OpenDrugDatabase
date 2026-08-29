# Step 1 V2 — human sign-off

The comparison was made by a human, after the MCP outputs were frozen and
committed. Nothing was re-run to reach it.

```text
HUMAN_SIGNOFF: STEP1_PASS
PASS 9 / FAIL 0 / VALID_UNKNOWN 1   (denominator 10, threshold 8)
```

VALID_UNKNOWN does not count toward the pass total, so the pass stands on 9 of a
possible 9 answerable cases. Summarisation or paraphrase by a downstream AI was
not scored: the material judged is `sections[].text` as the slice returned it.

## Verdicts

| case | drug | selector | verify | verdict |
| --- | --- | --- | --- | --- |
| S1-01 | atorvastatin | section_codes | VERIFIED | **PASS** |
| S1-02 | metformin | section_locators | VERIFIED | **PASS** |
| S1-03 | levothyroxine | section_codes | VERIFIED | **PASS** |
| S1-04 | lisinopril | section_codes | VERIFIED | **PASS** |
| S1-05 | amlodipine | section_codes | VERIFIED | **PASS** |
| S1-06 | metoprolol | section_codes | VERIFIED | **VALID_UNKNOWN** |
| S1-07 | albuterol | section_codes | VERIFIED | **PASS** |
| S1-08 | losartan | section_codes | VERIFIED | **PASS** |
| S1-09 | gabapentin | section_codes | VERIFIED | **PASS** |
| S1-10 | omeprazole | section_codes | VERIFIED | **PASS** |

## Reasons

**S1-01 atorvastatin — PASS**

The adult starting dose and dose range were delivered from the document's own dosage section.

**S1-02 metformin — PASS**

The sections stating no code, 2.3 and 2.4, were both retrieved by position. The eGFR criteria and the contrast-imaging discontinuation, the 48-hour re-evaluation and the restart once renal function is stable are all present.

**S1-03 levothyroxine — PASS**

Timing relative to breakfast and the four-hour interval from drugs affecting absorption were both delivered.

**S1-04 lisinopril — PASS**

The neprilysin-inhibitor contraindication and the 36-hour interval were both delivered.

**S1-05 amlodipine — PASS**

The adult starting and maximum antihypertensive doses were delivered.

**S1-06 metoprolol — VALID_UNKNOWN**

The pinned document is a myocardial-infarction-only label. The adult hypertension starting dose and this product's release characteristic are genuinely absent from it, and ODD stopped at UNKNOWN rather than supplying either from outside the document. Does not count toward the pass total.

**S1-07 albuterol — PASS**

The dosing interval, the maximum frequency and the warning on needing more doses than usual were all delivered.

**S1-08 losartan — PASS**

The starting dose, the maximum dose and the 25 mg starting dose for possible intravascular depletion were all delivered.

**S1-09 gabapentin — PASS**

TABLE 1 arrived whole in sections[].text: every creatinine-clearance band, the proportional reduction below 15, the hemodialysis maintenance rule, and the post-dialysis supplements of 125/150/200/250/350 mg.

**S1-10 omeprazole — PASS**

The instruction to avoid concomitant clopidogrel and to consider alternative anti-platelet therapy was delivered.

## The three worth naming

**S1-02** is the case the codeless-section fix existed for. In V1 the two
answering sections state no `<code>`, could not be named, and four of five gold
claims went unanswered. Named by position, both came back with the eGFR criteria
and the contrast-imaging instructions intact.

**S1-09** failed the V1 human audit for a reason worth remembering: the V1 gold
cited TABLE 1 but listed two of its five bands, so a partial delivery matched
everything the gold asked for. Gold V2 demands the whole table, and the whole
table arrived.

**S1-06** remains VALID_UNKNOWN, and that is the correct answer rather than a
shortfall. The pinned identity is a myocardial-infarction-only label; the
hypertension dose the question asks for is genuinely not in it, and ODD stopped
at UNKNOWN instead of supplying one from elsewhere. That is a fact about the
caller-supplied identity, not about ODD.

## What this does not change

The V1 outcome stands as recorded: 7 pass, 2 fail, STEP1_FAIL. This is a fresh
run against a corrected gold, not a revision of the old one. The protocol, gold
V2, the run plan and the MCP outputs are unchanged by this sign-off; only this
record is new.

## Fingerprints at sign-off

```text
protocol                  c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9
gold V2 fingerprint       864cd8707dab6b0c1bc543e5f1e1c1257808c2c713081081d0d22b2dd7e1d4bc
gold V2 manifest          060b2f8c6f0a72d56a7538e95c3a832eb6a8685e7a8e6f2590f3f91da43c798c
MCP V2 output fingerprint 6bbf13eb0d02c569a75ecd9db6d0b139a1d733ab099276ce82fd593a2dd055df
code commit               c9698676d0ca8e74136efd69de904936ca51eccb
run plan commit           b5631f8   (committed before the run)
MCP output commit         2b3239d
```

Run conditions: network attempts 0, data tree identical True (23417 files either side).
