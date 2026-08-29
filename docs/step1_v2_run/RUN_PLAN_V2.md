# Step 1 V2 — run plan, frozen before any MCP call

Identities come from the Gold V2 manifest and the questions from the frozen
protocol. No gold case file was opened to build this plan, and none will be
opened to build an answer: what this run freezes is the primary-source text the
slice returns.

- protocol `c0775cf92c49e685ec0a9deaf816a1198d72cd46996cbbc03193cef1ac60fed9`
- gold V2 fingerprint `864cd8707dab6b0c1bc543e5f1e1c1257808c2c713081081d0d22b2dd7e1d4bc`
- code commit `c9698676d0ca8e74136efd69de904936ca51eccb`

## What each case will ask for

| case | drug | selector | value |
| --- | --- | --- | --- |
| S1-01 | atorvastatin | section_codes | `34068-7`, `42229-5` |
| S1-02 | metformin | section_locators | `/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[3]/section[1]`<br>`/document[1]/component[1]/structuredBody[1]/component[5]/section[1]/component[4]/section[1]` |
| S1-03 | levothyroxine | section_codes | `34068-7`, `42229-5` |
| S1-04 | lisinopril | section_codes | `34070-3`, `34073-7` |
| S1-05 | amlodipine | section_codes | `42229-5`, `34068-7` |
| S1-06 | metoprolol | section_codes | `34067-9`, `34068-7`, `43678-2`, `34070-3` |
| S1-07 | albuterol | section_codes | `34068-7`, `42229-5`, `43685-7` |
| S1-08 | losartan | section_codes | `42229-5`, `34068-7` |
| S1-09 | gabapentin | section_codes | `42229-5` |
| S1-10 | omeprazole | section_codes | `42229-5`, `34073-7` |

## Why S1-02 is the one case that changes

Both sections that answer the metformin question state no `<code>` of their own.
In the V1 run the index reported their code as `UNKNOWN`, asking for that string
returned nothing, and four of five gold claims went unanswered. Here the two
positions are named exactly, as the index reports them.

Every other case asks for exactly what the V1 run asked for. S1-09 keeps its code
selector: in V1 that returned the section carrying TABLE 1 whole, a single
1592-character passage holding every band and every footnote.

## What this run will not do

- no gold answer text is generated
- no AI summary or paraphrase
- no comparison against gold
- no claim scoring
- no PASS/FAIL verdict
- Drugs@FDA is not requested
