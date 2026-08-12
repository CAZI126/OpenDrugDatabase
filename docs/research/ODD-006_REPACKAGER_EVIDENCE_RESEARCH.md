# ODD-006 repackager evidence research

- Overall ODD-006 status: `POPULATION_MEASUREMENT_BLOCKED`
- Candidate-local evidence status: `DIRECT_OFFICIAL_EVIDENCE_AVAILABLE` (narrow finding only)
- Development slice status: `LIVE_VERTICAL_SLICE_PASS`
- Scope: ODD-006 pre-implementation research only
- Candidate evidence captured: 2026-08-10
- Official documentation checked/captured: 2026-08-10–2026-08-11
- Repository baseline: `67a50c365a3c889ad2395cc78648ae71384f1d5e`

This document separates four kinds of statement:

- **FACT** — a contract, definition, or limitation stated by an official FDA, NLM, or
  DailyMed source.
- **OBSERVATION** — a value read from retained exact response bytes or the frozen ODD-005
  evidence.
- **POLICY** — a proposed ODD decision rule, not a fact asserted by the source.
- **UNKNOWN** — not established by the reviewed official evidence.

No candidate was selected or ingested during the original candidate-evidence research. A later
development-only technical validation slice selected, ingested, and verified one SPL without
changing schema v5, package version 0.5.0, or the regulatory selection policy. The minimal scope
guard added afterward is audited separately from the original research observations.

## 1. Executive conclusion

**Overall conclusion: `POPULATION_MEASUREMENT_BLOCKED`; core role model not justified.** The
earlier `DIRECT_OFFICIAL_EVIDENCE_AVAILABLE` conclusion is retained only as a candidate-local
finding about the exact records below. It is not an overall ODD-006 decision, does not establish a
closed-world application family, and does not justify a general single-winner or core role model.

The official openFDA NDC representation has an explicit `openfda.is_original_packager` field,
documented as indicating whether a drug has been repackaged for distribution. The retained
response contains literal `true` values for every NDC product row belonging to the NIVAGEN and
Umedica candidates. Each response is joined to the frozen candidate by set ID and to its exact
cached SPL revision by `spl_id`/document ID; the official label response independently supplies
the same set ID, document ID, and version. These are candidate-local positive submitted-data
assertions; they are not evidence that a company or application is globally non-repackaging, and
they are not inferred from a missing marker. See the [openFDA Drug NDC field reference, p.1](https://open.fda.gov/fields/drugndc_reference.pdf)
and [Drug NDC overview](https://open.fda.gov/apis/drug/ndc/) (sources S6 and S5; accessed
2026-08-11).

The three RemedyRepack candidates have the opposite positive evidence: each exact SPL contains a
structured product-source NDC, the official label API exposes that source as
`original_packager_product_ndc`, and the retained label affirmatively identifies the product as
repackaged and distributed by RemedyRepack. FDA's current SPL validation guide requires a product
source when an establishment operation is Repack (`C73606`) or Relabel (`C73607`), and conversely
requires one of those operations when a non-salvage product has a source reference. See
[SPL Implementation Guide, Version 1 Revision 202312080859, §§3.2.2 and 4.1.4, pp.73–74 and 107–109](https://www.fda.gov/media/84201/download?attachment=)
(source S1; accessed 2026-08-11).

Candidate research classifications are therefore:

| Candidate | Research classification | Basis |
| --- | --- | --- |
| NIVAGEN v17 | `NON_REPACKAGER_DIRECTLY_PROVEN` | Explicit `is_original_packager=true` on all four exact-identity NDC records |
| Umedica USA v1 | `NON_REPACKAGER_DIRECTLY_PROVEN` | Explicit `is_original_packager=true` on all four exact-identity NDC records |
| RemedyRepack 70518-3848 v8 | `REPACKAGER_PROVEN` | Source NDC 75834-258, SPL product-source structure, affirmative repackaging statement |
| RemedyRepack 70518-3783 v8 | `REPACKAGER_PROVEN` | Source NDC 75834-256, SPL product-source structure, affirmative repackaging statement |
| RemedyRepack 70518-4321 v2 | `REPACKAGER_PROVEN` | Source NDC 75834-257, SPL product-source structure, affirmative repackaging statement |

This conclusion is deliberately narrow. It establishes the packaging role asserted for these
five exact SPL revisions. It does not prove that a company never acts as a repackager for another
product. It is also an FDA-published representation of data submitted by firms, not an independent
FDA audit or clinical validation. FDA expressly says NDC Directory content is labeler-submitted
and not verified by FDA. See [NDC Product File Definitions, “Important Considerations”](https://www.fda.gov/drugs/drug-approvals-and-databases/ndc-product-file-definitions)
(source S4; accessed 2026-08-11).

For candidate-local role assertions, policy A remains the most conservative option considered in
the original research. No general role-family policy is approved by this report. In particular,
reusing the ODD-005 exact-lexical output as a regulatory-role discovery universe is
`INTENDED_USE_SCOPE_VIOLATION`, and the later population measurement cannot be used to justify a
core role model. A technical
parser-validation sample must remain separate from application, labeler, manufacturer, and
product-family representation.

### Superseding post-research evidence corrections

Atorvastatin is permanently `DEVELOPMENT_CONSUMED` and must not be reclassified as validation or
holdout. The retained technical artifact records `selected/ingested/verified = 1/1/1` for set ID
`7c58bf4a-4a92-4db8-89bc-4de1b5831efc`, expected and observed version 17, under
`TECHNICAL_VALIDATION_SPL_SAMPLE`. This proves that one real SPL passed the technical parser and
artifact-verification path; it is not a regulatory winner or a representative of the application
or all labelers. Role coverage is `PARTIAL`: UMEDICA remains the application sponsor, inbound
source evidence covers NIVAGEN product NDCs 75834-256, 75834-257, and 75834-258, and it is not
inherited by uncovered product NDC 75834-255.

The population observation is descriptive only:

- Numerator 2,897 divided by denominator 12,014 is 24.11353421008823%, with a Wilson 95% interval
  of 23.3569%–24.8867%.
- The frozen Kill gate defined a population based on current human prescription drug-label
  records. The observed artifact instead used the openFDA drug/NDC product export. Those
  populations do not match, completeness is false, and threshold application is `NOT_APPLIED`.
- The 1,897 count is not a role conflict, field conflict, regulatory contradiction, or semantic
  conflict. It is the number of product-NDC string identities associated with more than one
  distinct canonical-record SHA-256. A semantic denominator, identity list, and representative
  examples were not retained, so no further interpretation is supported.
- The 48,855 count is record-scoped: among 136,921 unique canonical NDC export records, 48,855
  lack the `is_original_packager` key in the harmonized `openfda` object. Null and empty-array
  shapes are distinct categories. This was counted before Atorvastatin exclusion and is not an
  application, labeler, non-repackager, or ingredient rate.

The population result therefore remains `POPULATION_MEASUREMENT_BLOCKED`; it must not be cited as
evidence for `CORE_ROLE_MODEL_JUSTIFIED`. The exact-byte, sidecar-hashed claim-provenance audit
carrying these corrections has SHA-256
`9fc160659b86546a802bad2bb46213b1ac12723f29aabf1c9bcb03fb7edb5bae`.

## 2. Frozen inputs

### Repository

| Input | Frozen value |
| --- | --- |
| Branch | `main` |
| HEAD and `origin/main` | `67a50c365a3c889ad2395cc78648ae71384f1d5e` |
| Package version | `0.5.0` |
| SQLite schema | v5 |
| ODD-005 run | `1c72cf95-44f7-5c34-95ff-cc5689303b71` |
| ODD-005 enrichment snapshot | `75ab3852-a58e-5eaa-ad55-35fec3a5e06f` |
| ODD-004 parent canonical SHA-256 | `af02855e7b8c998ae79d7f9f1a759e5f172c5a49cbb9a35f8f7afc103187a369` |

### Parent artifact integrity

The parent was opened read-only and immutable. The repository verifier passed all nine checks:
database presence and hash, item order, run hash, evidence hashes, assertion sources, filesystem
manifest presence and hash, and response hashes.

| Parent artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `database/odd.sqlite3` | 37,736,448 | `e02bcc6717e80cf8c8f13cbb2cc4f7a65d6c364b41f041421d48a35933f904b9` |
| `reports/report.json` | 2,772 | `bdfc80e3911deed35fbc982b0aa6eeb75fb192ea30026e18f458b356582de0a6` |
| snapshot `manifest.json` | 284,986 | `e7edb4371f0eaf4ce98f88c03951455348bd0debbc54a49123544432babbbaab` |

The frozen run has 429 retained detail responses, 3 execution records, 6,149 snapshot assertions,
2 immutable decision revisions, and 1 item state. Its canonical report records 403 candidates,
398 proven ineligible, 5 unknown, 403/403 Tier-1 completion, 13/13 Tier-2 completion, no selected,
ingested, or verified candidate, no source drift, no conflict, and status
`COMPLETED_WITH_UNRESOLVED_ITEMS`. The 13 recorded failures are the preserved earlier HTTP 406
attempts; they are not new research requests.

### Research isolation

All additional response bodies and HTTP headers are retained under the ignored directory:

```text
D:\OpenDrugDatabase\data\live\odd006-repackager-research-20260810
|-- official-api
`-- official-docs
```

The ODD-005 database, snapshot, evidence, and artifacts were not copied into or modified by that
directory.

This ignored directory was created by the earlier Windows research pass and was reused in place;
it was not moved to the newly suggested `data/research` path because relocation would add no
evidentiary value and would complicate the retained hash trail. The 2026-08-11 resumption made
**zero additional network requests and downloaded zero additional bytes**; the 25 retained
official bodies were sufficient to finish the identity and policy audit.

## 3. Five unresolved candidates

The ODD-004 search candidate's `labeler` column was null. The labeler shown below is instead the
structured SPL author organization (`document/author/assignedEntity/representedOrganization`),
with its DUNS identifier. That distinction prevents a title string from becoming role evidence.

| Candidate ID | Set ID | Version / published | Title | Structured SPL labeler | Product NDC(s) |
| --- | --- | --- | --- | --- | --- |
| `02506372-f7bf-5595-b8f0-2b0fd92e389c` | `7c58bf4a-4a92-4db8-89bc-4de1b5831efc` | 17 / 2025-12-10 | ATORVASTATIN CALCIUM TABLET [NIVAGEN PHARMACEUTICALS, INC.] | NIVAGEN PHARMACEUTICALS, INC.; DUNS `052032418` | 75834-255, 75834-256, 75834-257, 75834-258 |
| `3b3b3e6b-e3aa-5905-b917-eda2abc8a1ab` | `5a7594ca-30be-4350-827f-ef745a2a7e18` | 1 / 2026-02-16 | ATORVASTATIN CALCIUM TABLET [UMEDICA LABORATORIES USA INC.] | Umedica Laboratories USA Inc.; DUNS `119579082` | 60290-039, 60290-040, 60290-041, 60290-042 |
| `8221e050-e45a-58d2-b1f9-056cbf1d9f93` | `6600f22e-d303-4fe3-8212-accd6fb06e62` | 8 / 2026-06-10 | ATORVASTATIN CALCIUM TABLET [REMEDYREPACK INC.] | REMEDYREPACK INC.; DUNS `829572556` | 70518-3848 |
| `8abbdcba-605f-5faa-b765-bb060c3fcc9f` | `8821431a-c387-4b75-9540-f92bd455e961` | 8 / 2026-06-08 | ATORVASTATIN CALCIUM TABLET [REMEDYREPACK INC.] | REMEDYREPACK INC.; DUNS `829572556` | 70518-3783 |
| `a3750f5c-bc6a-56d2-a7da-1683ef2eecb3` | `604a011e-6c64-4895-8f6e-d28f119c4c22` | 2 / 2025-10-06 | ATORVASTATIN CALCIUM TABLET [REMEDYREPACK INC.] | REMEDYREPACK INC.; DUNS `829572556` | 70518-4321 |

Package NDCs retained in the official responses are:

- NIVAGEN: each of 75834-255 and 75834-256 with suffixes 01, 05, 50, 90; 75834-257
  with 01, 25, 50, 90; and 75834-258 with 01, 02, 50, 90.
- Umedica USA: each of 60290-039 through 60290-042 with suffixes 01, 02, 03, 04.
- RemedyRepack: 70518-3848-0/-1/-2, 70518-3783-0/-1/-2/-3, and 70518-4321-0.

For all five candidates, the frozen ODD-005 `REPACKAGED_PRODUCT` assertions are `UNKNOWN` at
Tier 0, Tier 1, and Tier 2. Tier 0 search metadata did not expose the fact; Tier 1 DailyMed
packaging JSON did not document it; and the existing Tier 2 extractor intentionally treated the
absence of `C73606`/`C73607` under its reviewed locator as unknown. This research does not rewrite
those assertions.

### Restored candidate identity and product facts

Publication date below is the DailyMed search-result value. Effective time is the value in the
exact SPL document; the two fields are deliberately not conflated. The ODD-004 search `labeler`
field was null for every row. The names in the labeler column below come from the official NDC
`labeler_name` field, while the separately reported author comes from the SPL represented
organization. These sources agree for the five records but remain distinct role assertions.

| Candidate | Set ID | Expected / observed version | Publication / effective date | Search title | SPL document type | SPL author / represented organization |
| --- | --- | --- | --- | --- | --- | --- |
| NIVAGEN | `7c58bf4a-4a92-4db8-89bc-4de1b5831efc` | 17 / 17 | 2025-12-10 / 2025-12-09 | ATORVASTATIN CALCIUM TABLET [NIVAGEN PHARMACEUTICALS, INC.] | `34391-3`, HUMAN PRESCRIPTION DRUG LABEL | NIVAGEN PHARMACEUTICALS, INC.; DUNS `052032418` |
| Umedica USA | `5a7594ca-30be-4350-827f-ef745a2a7e18` | 1 / 1 | 2026-02-16 / 2026-01-30 | ATORVASTATIN CALCIUM TABLET [UMEDICA LABORATORIES USA INC.] | `34391-3`, HUMAN PRESCRIPTION DRUG LABEL | Umedica Laboratories USA Inc.; DUNS `119579082` |
| Remedy 3848 | `6600f22e-d303-4fe3-8212-accd6fb06e62` | 8 / 8 | 2026-06-10 / 2026-06-09 | ATORVASTATIN CALCIUM TABLET [REMEDYREPACK INC.] | `34391-3`, HUMAN PRESCRIPTION DRUG LABEL | REMEDYREPACK INC.; DUNS `829572556` |
| Remedy 3783 | `8821431a-c387-4b75-9540-f92bd455e961` | 8 / 8 | 2026-06-08 / 2026-06-05 | ATORVASTATIN CALCIUM TABLET [REMEDYREPACK INC.] | `34391-3`, HUMAN PRESCRIPTION DRUG LABEL | REMEDYREPACK INC.; DUNS `829572556` |
| Remedy 4321 | `604a011e-6c64-4895-8f6e-d28f119c4c22` | 2 / 2 | 2025-10-06 / 2025-10-02 | ATORVASTATIN CALCIUM TABLET [REMEDYREPACK INC.] | `34391-3`, HUMAN PRESCRIPTION DRUG LABEL | REMEDYREPACK INC.; DUNS `829572556` |

| Candidate | Official NDC labeler | Product NDC(s) | Package NDC(s) | Marketing category | Dosage form / route | Structured active ingredient |
| --- | --- | --- | --- | --- | --- | --- |
| NIVAGEN | NIVAGEN PHARMACEUTICALS, INC. | 75834-255, -256, -257, -258 | 75834-255-{01,05,50,90}; 75834-256-{01,05,50,90}; 75834-257-{01,25,50,90}; 75834-258-{01,02,50,90} | ANDA (`C73584`) | TABLET (`C42998`) / ORAL (`C38288`) | ATORVASTATIN; active moiety ATORVASTATIN. The manufactured-product name is Atorvastatin calcium. |
| Umedica USA | Umedica Laboratories USA Inc. | 60290-039, -040, -041, -042 | Each product NDC with suffixes 01, 02, 03, 04 | ANDA (`C73584`) | TABLET (`C42998`) / ORAL (`C38288`) | ATORVASTATIN; active moiety ATORVASTATIN. The manufactured-product name is Atorvastatin calcium. |
| Remedy 3848 | REMEDYREPACK INC. | 70518-3848 | 70518-3848-0, -1, -2 | ANDA (`C73584`) | TABLET (`C42998`) / ORAL (`C38288`) | ATORVASTATIN; active moiety ATORVASTATIN; source product NDC 75834-258 |
| Remedy 3783 | REMEDYREPACK INC. | 70518-3783 | 70518-3783-0, -1, -2, -3 | ANDA (`C73584`) | TABLET (`C42998`) / ORAL (`C38288`) | ATORVASTATIN; active moiety ATORVASTATIN; source product NDC 75834-256 |
| Remedy 4321 | REMEDYREPACK INC. | 70518-4321 | 70518-4321-0 | ANDA (`C73584`) | TABLET (`C42998`) / ORAL (`C38288`) | ATORVASTATIN; active moiety ATORVASTATIN; source product NDC 75834-257 |

The exact source locators used to reconstruct those fields are:

| Fact | Exact locator |
| --- | --- |
| Search identity, title, publication, product type | ODD-retained candidate JSON `$.setid`, `$.spl_version`, `$.title`, `$.published_date`, `$.product_type` |
| SPL identity and document type | `/document/setId/@root`, `/document/versionNumber/@value`, `/document/effectiveTime/@value`, `/document/code/@{code,displayName}` |
| SPL author / represented organization | `/document/author/assignedEntity/representedOrganization/{name,id/@extension}` |
| Product and package NDC | `/document//manufacturedProduct/manufacturedProduct/code/@code`; `/document//containerPackagedProduct/code/@code` |
| Marketing category | `/document//approval/code/@{code,displayName}` and NDC JSON `/results/{row}/marketing_category` |
| Dosage form and route | `/document//manufacturedProduct/manufacturedProduct/formCode/@{code,displayName}`; `/document//routeCode/@{code,displayName}` |
| Active ingredient / active moiety | `/document//manufacturedProduct/manufacturedProduct/ingredient[@classCode='ACTIB']/ingredientSubstance/name`; its `activeMoiety/activeMoiety/name` |
| Original-package assertion | NDC JSON `/results/{row}/openfda/is_original_packager/0` |
| Repack/relabel source product | `/document//asEquivalentEntity/definingMaterialKind/code/@code`; label JSON `/results/0/openfda/original_packager_product_ndc` |

### Frozen ODD-005 assertions and winner-relevant fields

The three assertion IDs in each row are the immutable Tier 0 / Tier 1 / Tier 2
`REPACKAGED_PRODUCT` assertions. All are `UNKNOWN`; the research classification in the final
column is a new finding, not a mutation of those records. The ranking tuple is exactly the current
policy's `(numeric source version, publication date)` score, ordered descending. It is reported
for reproducibility and was not applied during this research.

| Candidate | Frozen assertion IDs (T0 / T1 / T2) | Why ODD-005 remained UNKNOWN | Winner-relevant fields | Research classification |
| --- | --- | --- | --- | --- |
| NIVAGEN | `d9e8972c-19f8-5319-a83c-47ed84f7ccc1` / `8f9e0d3a-44cf-5bc3-a8c2-586042203b14` / `37643dd4-2248-5e3e-9d85-0fb16af3d0b1` | Search and packaging schemas had no documented role field; no `C73606/C73607` was found, whose absence was correctly non-probative. The explicit FDA NDC field was outside the frozen extractor's sources. | `(17, 2025-12-10)`; every other required eligibility assertion is proven and no source drift/conflict exists | `NON_REPACKAGER_DIRECTLY_PROVEN` |
| Umedica USA | `82c4b3a9-39b6-5e03-bab6-35700b6b1f11` / `d2e2810c-65a5-554a-a400-6ff9e258a7d4` / `97d45409-56b4-546f-9b9f-c516e12d8cfa` | Same frozen extractor boundary as NIVAGEN; field absence was not converted to false. | `(1, 2026-02-16)`; every other required eligibility assertion is proven and no source drift/conflict exists | `NON_REPACKAGER_DIRECTLY_PROVEN` |
| Remedy 3848 | `0b14418a-77eb-52d3-8f8e-e3e0d44a201e` / `11652bb9-8a39-58fc-a675-48ceb5923e23` / `639bd0ea-f787-5708-bcda-ee816907acf5` | The frozen extractor checked the operation-code locator only; it did not interpret the structured source NDC plus affirmative label statement. | `(8, 2026-06-10)` before the new role evidence; every other required assertion is proven | `REPACKAGER_PROVEN` |
| Remedy 3783 | `b2a73a41-4b90-5d93-83e0-0a9ad25e3461` / `69d8450d-dac7-5e17-b801-dfa8fd6f9f88` / `9f9309d0-9266-569a-b0b4-017bbe11fab8` | Same frozen extractor boundary as Remedy 3848. | `(8, 2026-06-08)` before the new role evidence; every other required assertion is proven | `REPACKAGER_PROVEN` |
| Remedy 4321 | `9049d7f9-91c1-55e8-9930-80451dce45b4` / `402e8d42-4a32-5257-bc32-4ea2363f2926` / `4441d45f-5e65-54e0-bcac-611129efec68` | Same frozen extractor boundary as Remedy 3848. | `(2, 2025-10-06)` before the new role evidence; every other required assertion is proven | `REPACKAGER_PROVEN` |

| Candidate | Search metadata SHA-256 | Tier-1 packaging SHA-256 | Tier-2 XML SHA-256 | FDA NDC response SHA-256 | FDA label response SHA-256 |
| --- | --- | --- | --- | --- | --- |
| NIVAGEN | `0e17899d28f0fcb63a49c07d0c80bbf5fd7fe9891c00189b05d0657d2283b000` | `bb25b25afa8944a936d1d7c8bad23737a269cc8daa7fb631e2205a8f1a55e805` | `bad95508b99be9b19636428930f0eee4a97cac2e45fb42de4a8bdcb5a570e886` | `befb5605417a6bfa2e81f0e39eab830dfc3eedf98287a1b6b92178b14ffb5ff7` | `3e27d533e96f656a42a567fa011cc836a0c93ccf9efa67cf04f0f3835550530d` |
| Umedica USA | `76c34155cd2c903766f4df8ca80427f728c8a69f965534abefa80a57c9783538` | `49bce0a1c0e3766cff012123e8b5f84211e2156bbbe9e3e3b3e857f789498c9c` | `9302307d6343e9a2b10a886c186d8217f2d963c091b1fd3a633fd18e0a98a8ed` | `8fd977dcf1d8df87f80a6ad884a2f70636d466489aa77027351b45ffd6958144` | `0b468c60b5e5234922bed39746714534782f8eefac9e786b0fbfd94339c77236` |
| Remedy 3848 | `4aa9e4108e7f176f9619c96a15eab41fdea03e4eee52d0878fc193978f5daaef` | `d11a05ff52a40a29c64f148880b4370f74007804a9b19bbb60f7d108695f7149` | `1a445a39c267c342ed60003cb3925ea756d3c88ccc7163e38da3857dd8a0d786` | `a28b9e1298f668c7adcf47216b111d1addb69c23ad8b81f3b57807c6b6a45e58` | `d41462f0fed7bc0f5f04587ebf275d31ea40593ffa8c4d1a7c6f5f9018832ea4` |
| Remedy 3783 | `179aeeec30e55c3d3903bdd225893a4de8426dc858a692e561011aedfb609eba` | `ed67c9e2ae77b4f28bbc7e921a3ba1cc7a4ca72c8625f0ed2038e9e6eccf190d` | `9f47d7c3a19ba2e1dd1ca9b862734ab556f65c5609feeb7203cb00868855f399` | `ef8e7dce06dcf063ead2f37b46e7b9f4b80be81a331b0630c58690ea317a3733` | `63bc29727529a33a30fbb9584983cebcf53bdfc4e135b92d916a43fbc5e6890a` |
| Remedy 4321 | `6dc3fa834ddb562a3ff0c1be1844d18643266a7b60bcd62fa2f6caa8dcb07615` | `abbfb5c42cf2428f405d135094824fe82b8b766df7965e3e132dd9893460523e` | `5ef0465aca2fbec4acbd476f113f2505cfccb5a0ee54b5a633fbea7de7163d57` | `f5cc7316ee12155e4160c302785baf0739f76b51bd3fe4e0e261f2e915cd688a` | `45f83d145d5d94a2601cecd6968dd6c4d8ccd3fdcbe80e90a04663e643903b4e` |

## 4. Official definitions

| Role | Official meaning or representation | Consequence for this research |
| --- | --- | --- |
| Repack / repackaging | FDA describes removal from the received container and placement into a different container without changing composition or formulation. Repackaging may also include applying a different label. [Reporting Amount Technical Conformance Guide, February 2024, Revision 1, §IV.C, p.7, footnote 20](https://www.fda.gov/media/153612/download) (S2) | Product-specific positive evidence; do not infer from company name. |
| Relabel / relabeling | FDA describes changing an existing package label without repackaging or changing composition/formulation. [Same guide, §IV.C, p.7, footnote 21](https://www.fda.gov/media/153612/download) (S2) | Distinct from repackaging; source-NDC structure alone proves the disjunction unless another fact disambiguates it. |
| FDA business operations | FDA's current controlled list maps `C73606` to REPACK, `C73607` to RELABEL, `C43360` to MANUFACTURE, `C84731` to PACK, `C84732` to LABEL, `C201565` to DISTRIBUTE, and `C73608` to private-label distribution. [Business Operation](https://www.fda.gov/industry/structured-product-labeling-resources/business-operation) (S3; accessed 2026-08-11) | Use codes only at their documented structured locator. |
| Labeler | NDC Directory says a labeler may be a manufacturer (including repackager/relabeler) or the private-label entity whose name appears on the product. SPL represents one labeler in the document author organization with name and DUNS. [NDC Product File Definitions](https://www.fda.gov/drugs/drug-approvals-and-databases/ndc-product-file-definitions) (S4); [SPL guide §4.1.2, p.106](https://www.fda.gov/media/84201/download?attachment=) (S1) | Being the labeler does not prove manufacturer, original packager, or non-repackager. |
| Manufacturer / establishment | SPL records establishments separately from the labeler and assigns each one or more business-operation codes that must agree with its most recent registration. [SPL guide §4.1.4, pp.107–109](https://www.fda.gov/media/84201/download?attachment=) (S1) | A manufacturer name or MANUFACTURE operation is not by itself a closed-world negation of REPACK/RELABEL. |
| Distributor | A firm distributing under its own name may be the NDC labeler; DISTRIBUTE and private-label distribution also have distinct operation codes (S3, S4). The reviewed sources did not supply a single exhaustive definition that collapses these roles. | Distributor, labeler, and original packager are not interchangeable roles. |
| Applicant / application holder | FDA defines the applicant or drug sponsor as the entity responsible for marketing the new drug and regulatory compliance; it is often, but not necessarily, a manufacturer. [Drug Development and Review Definitions, “Applicant (Drug Sponsor)”](https://www.fda.gov/drugs/investigational-new-drug-ind-application/drug-development-and-review-definitions) (S13; accessed 2026-08-11) | Drugs@FDA sponsor identity is not repackager-role evidence. |

The FDA SPL guide's document model is the controlling implementation source here. An older or
generic HL7 SPL representation was not used to override FDA-specific validation procedures.

## 5. SPL and DailyMed evidence

### Structured relationships

**FACT.** The current FDA SPL guide represents a product source as an equivalent entity whose
material code is the source product item code. Rule 3.2.2.11 requires a source reference when an
operation is Repack or Relabel. Rule 4.1.4.13 requires Repack or Relabel when a non-salvage product
has a source reference. The guide also keeps the author labeler, registrant, establishments, and
establishment operations in different structures. [SPL guide, §§3.2.2, 4.1.2–4.1.4](https://www.fda.gov/media/84201/download?attachment=)
(S1).

**OBSERVATION.** The exact NIVAGEN and Umedica XML revisions contain no product-source reference.
Their retained operation sets are respectively `C25391,C43360` and
`C25391,C43360,C84731`. Those facts corroborate original-product status but are not used as direct
negative proof: an absent source or absent operation is not evidence of absence.

**OBSERVATION.** Each Remedy XML has an exact source product code:

| Set ID | Exact SPL document ID | Version | SPL source NDC | Affirmative label sections |
| --- | --- | ---: | --- | --- |
| `6600f22e-d303-4fe3-8212-accd6fb06e62` | `53d52358-aa1b-cc96-e063-6294a90a81fb` | 8 | 75834-258 | LOINC 34069-5 and 42230-3 |
| `8821431a-c387-4b75-9540-f92bd455e961` | `53846d12-8904-b025-e063-6294a90abcf3` | 8 | 75834-256 | LOINC 34069-5 and 42230-3 |
| `604a011e-6c64-4895-8f6e-d28f119c4c22` | `402e6f6e-bc5c-cd8c-e063-6294a90a7196` | 2 | 75834-257 | LOINC 34069-5 and 42230-3 |

The structured locator is
`/document//asEquivalentEntity/definingMaterialKind/code/@code`. The label sections affirmatively
state that RemedyRepack repackaged and distributed the product. The narrative is corroboration;
the structured source relationship and the FDA validation rules carry the role inference. The
absence of equivalent wording is never used for NIVAGEN or Umedica.

### DailyMed limitations

DailyMed states both that it presents the most recent company-submitted, in-use labeling and that
it does not contain a complete listing of labeling for FDA-regulated products. [DailyMed home,
“About DailyMed”](https://dailymed.nlm.nih.gov/dailymed/) (accessed 2026-08-11). Therefore neither
DailyMed as a corpus nor any optional field is closed-world (S10). Its omission cannot prove that a
candidate is an original package.

## 6. FDA cross-source evidence

### Exact joins

The additional evidence used three official endpoints:

1. `api.fda.gov/drug/ndc.json`, searched by exact `openfda.spl_set_id`, to obtain product rows and
   `is_original_packager` where present.
2. `api.fda.gov/drug/label.json`, searched by exact native `set_id`, to obtain the current label
   record, version, document ID, and harmonized source NDC where present.
3. `api.fda.gov/drug/drugsfda.json`, searched by `application_number:ANDA213853`, to distinguish
   the application sponsor from labeler/packaging roles.

All 11 captured API responses were HTTP 200 `application/json`, had exact bytes, SHA-256, headers,
ETag, and retrieval date retained, and used no off-origin redirect. The joins are:

| Candidate | NDC API facts | Label API identity facts | Research result |
| --- | --- | --- | --- |
| NIVAGEN | Four product records; `is_original_packager=[true]` on all four | set ID match; ID `4580fe3c-b524-3a14-e063-6294a90a34d3`; version 17; effective time 20251209 | `NON_REPACKAGER_DIRECTLY_PROVEN` |
| Umedica USA | Four product records; `is_original_packager=[true]` on all four | set ID match; ID `4999f880-cf37-837f-e063-6394a90a72d2`; version 1; effective time 20260130 | `NON_REPACKAGER_DIRECTLY_PROVEN` |
| Remedy 3848 | `is_original_packager` absent — not used | set ID/ID/version match; `original_packager_product_ndc=[75834-258]` | `REPACKAGER_PROVEN` with SPL source evidence |
| Remedy 3783 | `is_original_packager` absent — not used | set ID/ID/version match; `original_packager_product_ndc=[75834-256]` | `REPACKAGER_PROVEN` with SPL source evidence |
| Remedy 4321 | `is_original_packager` absent — not used | set ID/ID/version match; `original_packager_product_ndc=[75834-257]` | `REPACKAGER_PROVEN` with SPL source evidence |

There was no set-ID, document-ID, or version drift for any of the five candidates.

### Drugs@FDA is a different role axis

The captured Drugs@FDA response identifies UMEDICA as sponsor of ANDA213853 and harmonizes that
application to only the NIVAGEN and Umedica set IDs, their two document IDs, and eight product
NDCs. The three Remedy records cite the same application number in their submitted label, but do
not thereby become the application holder. Official Drugs@FDA data definitions have a distinct
`SponsorName` in the Applications table. [Drugs@FDA Data Files, definitions dated 2025-01-10](https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files)
(accessed 2026-08-11).

Thus, application holder, labeler, manufacturer, and packager are joinable facts on different
axes. Equality among names is at most a policy inference and is unnecessary for the five findings.

## 7. Closed-world analysis

| Source/field | Closed world? | Official limitation and permitted use |
| --- | --- | --- |
| DailyMed corpus | No | DailyMed says its labeling listing is incomplete. Presence is usable; absence is not. |
| NDC Directory | No | It contains only certain final marketed, labeler-submitted drugs, does not contain all listed drugs, and FDA does not verify each entry. |
| openFDA harmonized fields | No | Fields are attached only if applicable; not all records harmonize and exact-match failures leave fields absent. [openFDA fields, “Limits of harmonization”](https://open.fda.gov/apis/openfda-fields/) (accessed 2026-08-11). |
| Drugs@FDA | No | The official API says it includes most, not all, products approved since 1939. [Drugs@FDA overview](https://open.fda.gov/apis/drug/drugsfda/) (accessed 2026-08-11). |
| Explicit `is_original_packager=true` on an exact record | Candidate-local positive fact | Direct official representation for that exact joined revision; it does not close the surrounding corpus. |
| Explicit source NDC/product-source structure | Candidate-local positive fact | Direct evidence that the listed product derives from another packaged product; FDA rules bind it to Repack or Relabel, subject to the salvage exception. |

Consequences:

- Missing `is_original_packager`, `original_packager_product_ndc`, `C73606`, `C73607`, or a
  narrative phrase remains `UNKNOWN`.
- Labeler/manufacturer-name equality is not proof of original packaging.
- An ANDA number or sponsor match is not packaging-role proof.
- An NDC's existence and an ordinary-looking product title are not role proof.
- The positive fields used here are official assertions, but FDA's disclaimer means they are not
  independently verified business facts or clinical evidence.

## 8. Candidate-by-candidate findings

### 8.1 NIVAGEN, set `7c58bf4a-4a92-4db8-89bc-4de1b5831efc`, v17

- **OBSERVATION:** Four NDC response rows exactly match product NDCs 75834-255 through 75834-258.
  Each has `/results/{row}/openfda/is_original_packager/0 = true`.
- **OBSERVATION:** Native NDC `spl_id`, label API `id`, and cached XML document ID all equal
  `4580fe3c-b524-3a14-e063-6294a90a34d3`; set ID and v17 also agree.
- **OBSERVATION:** The cached XML author is NIVAGEN, and the structured operations observed are
  ANALYSIS and MANUFACTURE. The absent repack code/source is corroborative only.
- **Classification:** `NON_REPACKAGER_DIRECTLY_PROVEN` for this exact candidate revision.

### 8.2 Umedica Laboratories USA, set `5a7594ca-30be-4350-827f-ef745a2a7e18`, v1

- **OBSERVATION:** Four exact NDC rows, 60290-039 through 60290-042, each have
  `/results/{row}/openfda/is_original_packager/0 = true`.
- **OBSERVATION:** NDC `spl_id`, label API `id`, and cached XML ID all equal
  `4999f880-cf37-837f-e063-6394a90a72d2`; set ID and v1 agree.
- **OBSERVATION:** The cached SPL author is Umedica Laboratories USA, and the operation set
  contains ANALYSIS, MANUFACTURE, and PACK. Absences are not part of the proof.
- **Classification:** `NON_REPACKAGER_DIRECTLY_PROVEN` for this exact candidate revision.

### 8.3 RemedyRepack 70518-3848, set `6600f22e-d303-4fe3-8212-accd6fb06e62`, v8

- **OBSERVATION:** Missing `is_original_packager` is ignored.
- **OBSERVATION:** Label API has
  `/results/0/openfda/original_packager_product_ndc/0 = 75834-258`; cached SPL has the same
  structured source code and exact ID/version.
- **OBSERVATION:** Sections 34069-5 and 42230-3 affirmatively identify RemedyRepack as the
  repackaging/distribution party.
- **Classification:** `REPACKAGER_PROVEN`.

### 8.4 RemedyRepack 70518-3783, set `8821431a-c387-4b75-9540-f92bd455e961`, v8

- **OBSERVATION:** Missing `is_original_packager` is ignored.
- **OBSERVATION:** Official label source NDC and cached structured SPL source both equal
  75834-256; ID and version match the frozen candidate.
- **OBSERVATION:** Sections 34069-5 and 42230-3 carry the same affirmative repackaging role.
- **Classification:** `REPACKAGER_PROVEN`.

### 8.5 RemedyRepack 70518-4321, set `604a011e-6c64-4895-8f6e-d28f119c4c22`, v2

- **OBSERVATION:** Missing `is_original_packager` is ignored.
- **OBSERVATION:** Official label source NDC and cached structured SPL source both equal
  75834-257; ID and version match the frozen candidate.
- **OBSERVATION:** Sections 34069-5 and 42230-3 carry the affirmative repackaging role.
- **Classification:** `REPACKAGER_PROVEN`.

No candidate has `ROLE_CONFLICT`. None is classified from company reputation, title, an absent
string, labeler/manufacturer equality, application number, or NDC existence.

## 9. Policy comparison

“Clinical safety” below means the relative risk of misrepresenting regulatory/product variants.
None of the policies makes ODD a clinically validated database.

| Policy | Mis-selection risk | Mis-exclusion risk | Clinical safety | Provenance | Determinism | Manufacturer differences | Top-100 scalability | AI-client fit | Operations/update cost | Effect on current five |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| A — strict direct proof | Lowest when explicit evidence exists | Medium/high where harmonization is absent | High for role claims | Strong | Strong | Weak if only winner is exposed | Medium; more manual cases | Good for a single validated parser input; incomplete for variants | Medium | 3 proven repackagers excluded; 2 pass this role gate |
| B — exclude positive repackager only | Medium: unknowns can enter winner set | Low | Medium; uncertainty must remain visible | Strong if UNKNOWN is retained | Strong with a versioned rule | Weak in single-winner output | High | Reasonable if uncertainty is first-class | Low/medium | Same immediate 3/2 split, but changes behavior for future UNKNOWNs |
| C — role as preference | Medium/high | Low | Medium/low for claims about an “original” label | Good if score and uncertainty are retained | Strong only with a versioned score | Medium | High | Good for retrieval ranking, weaker for validation truth | Low/medium | 2 direct originals rank better; policy change still required |
| D — target application holder/original labeler | High if treated as equivalent to packaging role | High for legitimate variants | Low unless the product goal is redefined | Source facts are strong, but the role substitution is unsupported | Strong for the substituted rule | Low/medium | Medium | Poor if clients need manufacturer/route variants | Medium/high | Would privilege UMEDICA-related records for a different reason; not a repack proof |
| E — no single winner; retain label family | No winner mis-selection | Lowest | Highest preservation of product differences | Strong | Strong with canonical family order | Strongest | High, but data volume grows | Best for AI retrieval with explicit product/route/manufacturer context | High | All 5 retained with role evidence; 3 marked repackaged, 2 original |
| F — signed human override | Reviewer-dependent | Reviewer-dependent | Medium/high with governance | Strong only with evidence hash, reviewer, reason, expiry, and drift invalidation | Reviewer-dependent; deterministic after signing and versioning | Medium | Low/medium | Useful as an exception channel, not a default | Highest | Unnecessary for these 5 if direct field is accepted |

Policy A best preserves the stated ODD-005 validation-label contract and now has enough direct
evidence for these five. Policy E addresses a different, valuable requirement: retaining multiple
manufacturers, strengths, dosage forms, routes, and label families for downstream use. It should
be modeled separately rather than weakening the eligibility proof for the technical validation
label. Policy F remains a defensible fallback where official evidence is genuinely unavailable.

## 10. Recommended decision

Recommended status: **`POPULATION_MEASUREMENT_BLOCKED`** and
**`CORE_ROLE_MODEL_NOT_JUSTIFIED`**.

The exact candidate-local assertions remain useful provenance, but the measured product-export
population does not satisfy the frozen drug-label-record Kill gate. Its 24.11353421008823% value is
descriptive only, and no threshold was applied. The 1,897 duplicate-identity condition cannot be
promoted to a role or field conflict. A corrected population observation, with the preregistered
universe and retained semantic conflict details, is required before reconsidering a core role
model.

The immutable ODD-005 artifact remains manual and records 0/0/0. Separately, the later
development-only artifact records `LIVE_VERTICAL_SLICE_PASS` and 1/1/1 for NIVAGEN v17 under
`TECHNICAL_VALIDATION_SPL_SAMPLE`. Atorvastatin is `DEVELOPMENT_CONSUMED`; neither that sample nor
the observed population result may be reused as validation or holdout evidence.

## 11. Minimal ODD-006 implementation and remaining plan

1. Keep the implemented scope correction minimal: producer artifacts carry a literal
   `intended_use_scope`, consumers require an exact literal scope, and mismatches are recorded and
   rejected before selection or ingestion.
2. Preserve the distinct values `DAILYMED_CURRENT_HUMAN_RX_GENERIC_QUERY_RESULTS`,
   `VALIDATION_LABEL_EXACT_LEXICAL_SINGLE_ACTIVE`,
   `REGULATORY_ROLE_APPLICATION_FAMILY_DISCOVERY`, and
   `TECHNICAL_VALIDATION_SPL_SAMPLE`. Do not add adapters, a registry, a compatibility matrix, or
   scope-specific database tables.
3. Keep SQLite schema v5 and package version 0.5.0. Do not implement a schema-v6 family model from
   the blocked population result.
4. Retain the NIVAGEN v17 development artifact as a nonrepresentative parser-validation sample
   with `PARTIAL` role coverage. Do not convert it into an application or label-family winner.
5. Before any larger role model, repeat the population study only under an owner-approved,
   preregistered universe whose observed records match the frozen denominator. Retain enough
   evidence to define and inspect any duplicate-identity condition semantically.

The official NDC field reference describes `is_original_packager` as a string, while the captured
JSON represents it as an array containing a JSON boolean. ODD-006 must use a strict, versioned type
guard and fixtures based on retained bytes; it must not silently coerce arbitrary strings or
numbers.

## 12. Rejected approaches

- Treating an absent repackager word, source NDC, harmonized field, or operation code as proof of
  original packaging.
- Inferring role from a pharmaceutical-sounding company name or the RemedyRepack title alone.
- Treating labeler, manufacturer, distributor, registrant, or application sponsor as synonymous.
- Treating ANDA213853, approval status, or an NDC's existence as original-packager proof.
- Selecting a favorable official field while suppressing a contradictory one.
- Replacing the current non-repackager criterion with a new application-holder or brand policy in
  this research task.
- Adding openFDA or Drugs@FDA data to the immutable ODD-005 parent artifact.
- Using a nonofficial database, search snippet, company site, or LLM inference as candidate
  evidence.
- Downloading the full DailyMed archive, a purported “DailyMed v28,” or the remaining nine
  ingredients.
- Using a human override when direct official candidate evidence is already available.

## 13. Unresolved questions

1. openFDA documents the field's meaning, but not a versioned derivation algorithm or stability
   contract for the harmonized annotation. ODD must pin its extractor version and retain bytes.
2. The NDC field-reference type and observed JSON shape differ. The exact accepted representation
   needs explicit tests and conservative failure behavior.
3. How often will top-100 candidates lack harmonization? Absence rates must be measured by a later
   bounded pilot; missing fields must remain unknown.
4. A structured source reference proves Repack-or-Relabel under the FDA validation rule. Where no
   affirmative disambiguating evidence exists, should the existing exclusion treat both roles
   identically or preserve them as separate facts? That is a policy/modeling question.
5. FDA publishes submitted listing data without independently verifying each entry. A legal or
   audit-grade role guarantee would require a different assurance process.
6. Whether downstream AI clients need one parser-validation label, a canonical product family,
   or both should be specified independently of the repackager gate.
7. Historical reproducibility still requires exact cached responses because FDA/openFDA endpoints
   present current observations rather than a permanent historical snapshot contract.

## 14. Official source inventory

Source IDs below are the complete citations for the important claims in sections 1 and 4–8.
Each citation records the official URL, issuing authority, stated document version or revision
date, exact section/page/heading, directly supported fact, access date, and SHA-256 of the retained
body. “Not stated” is used where the official page or PDF did not publish a document revision; an
HTTP timestamp is not promoted into a document version.

| ID | Official source / issuing authority | Version or revision date | Section, page, or heading used | Fact directly supported | Access date | Retained body SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| S1 | [FDA SPL Implementation Guide](https://www.fda.gov/media/84201/download?attachment=), U.S. FDA | Version 1, Revision `202312080859` | §§3.2.2, 4.1.1–4.1.4; PDF pp.73–74, 105–109 | FDA SPL structures for product source, labeler, registrant/establishment and operations; Repack/Relabel source-reference validation rules | 2026-08-11 | `9845e23cb51ee2e7f493b17ed5729b2bc946040244e6f6da2d78c9491a41f983` |
| S2 | [Reporting Amount Technical Conformance Guide](https://www.fda.gov/media/153612/download), U.S. FDA | February 2024, Revision 1 | §IV.C/D; printed pp.7–10 | FDA descriptions of repackaging and relabeling and the source-NDC relationship | 2026-08-11 | `2117f60c3d7efaf869c7aa0b1b5dda70c26aeee309ea4c4a13d3678dbbd55364` |
| S3 | [Business Operation](https://www.fda.gov/industry/structured-product-labeling-resources/business-operation), U.S. FDA | Page modified 2023-09-26; no separate controlled-list version stated | “Business Operation” controlled-term table | `C73606` REPACK, `C73607` RELABEL, and manufacture, pack, label, distribute, private-label distribution operation codes | 2026-08-11 | `25009c3cfb11c4e17509d8f62e12fbfb3ae53b0410dd5ef39aecaf9947047245` |
| S4 | [NDC Product File Definitions](https://www.fda.gov/drugs/drug-approvals-and-databases/ndc-product-file-definitions), U.S. FDA | Page modified 2024-06-12; no separate data-dictionary version stated | “Important considerations” and product-file field definitions | Labeler scope; NDC Directory omissions; content is submitted by labelers and is not verified by FDA | 2026-08-11 | `b05f509ce450f8f9c377447b6653b9d419357af1898fd8d8f3cf11c12efc689d` |
| S5 | [Drug NDC API overview](https://open.fda.gov/apis/drug/ndc/), U.S. FDA/openFDA | Web documentation revision not stated | “Drug NDC Overview”, “Fields Harmonization”, “Disclaimer” | API source is NDC Directory; openFDA adds harmonized fields; labeler-submitted-data and medical-use limitations | 2026-08-11 | `9087b71a91891fac6b712cb1d63ec0f8626c5f5a3a1b009d90a603ae38128e89` |
| S6 | [Drug NDC field reference](https://open.fda.gov/fields/drugndc_reference.pdf), U.S. FDA/openFDA | PDF revision not stated | p.1, `is_original_packager`, `spl_id`, `spl_set_id` | `is_original_packager` indicates whether the drug has been repackaged for distribution; document/set identifiers support exact joins | 2026-08-11 | `968d551acc07f7f2987459f5951497e6a3fdee8d1c3bfa36049f0be5fd32f451` |
| S7 | [Drug label API overview](https://open.fda.gov/apis/drug/label/), U.S. FDA/openFDA | Web documentation revision not stated | “Drug Labeling Overview”, “Key Facts”, “Disclaimer” | Label API is based on submitted SPL labeling and is neither independently verified nor a clinical decision source | 2026-08-11 | `715db2043df249fc5f3d31e3cbb69c777a6de35c540850797154f797ea36ccbd` |
| S8 | [Drug label field reference](https://open.fda.gov/fields/druglabel_reference.pdf), U.S. FDA/openFDA | PDF revision not stated | pp.2–3, native ID/set/version and openFDA fields | Meaning of label document ID, set ID, version and harmonized manufacturer/NDC fields | 2026-08-11 | `7712f67d9b306679ae7be66eca61eefccfa34d2024195db31f35c70b3b4fe692` |
| S9 | [openFDA fields](https://open.fda.gov/apis/openfda-fields/), U.S. FDA/openFDA | Web documentation revision not stated | “Limits of harmonization” | Harmonized fields are conditional and may be absent; absence does not close the source universe | 2026-08-11 | `d6d2d1e112c5f5dc27726469a00abcac7e8fa7956a0f412b8c8e89dbfdc63e08` |
| S10 | [DailyMed](https://dailymed.nlm.nih.gov/dailymed/), U.S. National Library of Medicine / DailyMed | Web page revision not stated | “About DailyMed” | DailyMed presents current submitted in-use labeling but explicitly does not contain a complete listing | 2026-08-11 | `31c5eb88ef2e5ae7faf9e641cb30861c7561948aee30f71fc6725dbe8eb64280` |
| S11 | [Drugs@FDA Data Files](https://www.fda.gov/drugs/drug-approvals-and-databases/drugsfda-data-files), U.S. FDA | Page modified 2026-08-10; data definitions/ERD as of 2025-01-10 | “Applications” and “Products” table definitions | `SponsorName` belongs to the application relation and is separate from product and packaging roles | 2026-08-11 | `aa8314669606a333436883e3c129cafdfd0a3fb4394581e22c456d567eab5cf6` |
| S12 | [Drugs@FDA API overview](https://open.fda.gov/apis/drug/drugsfda/), U.S. FDA/openFDA | Web documentation revision not stated | Overview, Key Facts, Disclaimer | Dataset covers most rather than all approved products and therefore is not closed-world | 2026-08-11 | `ee794bb0f5deba3acd8b2bdffe395483804f22957f025ede5b1fc7facdedc948` |
| S13 | [Drug Development and Review Definitions](https://www.fda.gov/drugs/investigational-new-drug-ind-application/drug-development-and-review-definitions), U.S. FDA | Page modified 2015-08-20 | “Applicant (Drug Sponsor)” | Applicant/sponsor assumes marketing and regulatory responsibility and is not necessarily the manufacturer or packager | 2026-08-11 | `484d196cfc982234a570e98aca3b9b82206c164a736899ecf81ee25d91e7659b` |
| S14 | [Electronic Drug Registration and Listing System](https://www.fda.gov/drugs/guidance-compliance-regulatory-information/electronic-drug-registration-and-listing-system-edrls), U.S. FDA | Page modified 2026-02-05 | Registration and listing overview | Regulatory listing is a submission system; role assertions remain tied to the submitted SPL structures | 2026-08-11 | `98ad17d4f8c978d18e587255f85a9db2f3c3caa567227bb4a323d49efed384d4` |

### Candidate-specific official API observations

These are observation-specific sources rather than versioned specifications. All were captured on
2026-08-10 from U.S. FDA/openFDA as HTTP 200 `application/json`. The exact request URLs are shown;
the source field meanings come from S6 and S8.

| Candidate / source | Exact official URL | Locator and directly supported observation | Body SHA-256 |
| --- | --- | --- | --- |
| NIVAGEN NDC | `https://api.fda.gov/drug/ndc.json?search=openfda.spl_set_id:%227c58bf4a-4a92-4db8-89bc-4de1b5831efc%22&limit=100` | `/results/*/{product_ndc,spl_id,openfda/spl_set_id,openfda/is_original_packager}`: four exact product rows, each `is_original_packager=[true]` | `befb5605417a6bfa2e81f0e39eab830dfc3eedf98287a1b6b92178b14ffb5ff7` |
| NIVAGEN label | `https://api.fda.gov/drug/label.json?search=set_id:%227c58bf4a-4a92-4db8-89bc-4de1b5831efc%22&limit=1` | `/results/0/{id,set_id,version,effective_time}`: exact document ID, set ID and v17 | `3e27d533e96f656a42a567fa011cc836a0c93ccf9efa67cf04f0f3835550530d` |
| Umedica NDC | `https://api.fda.gov/drug/ndc.json?search=openfda.spl_set_id:%225a7594ca-30be-4350-827f-ef745a2a7e18%22&limit=100` | Same identity locators: four exact product rows, each `is_original_packager=[true]` | `8fd977dcf1d8df87f80a6ad884a2f70636d466489aa77027351b45ffd6958144` |
| Umedica label | `https://api.fda.gov/drug/label.json?search=set_id:%225a7594ca-30be-4350-827f-ef745a2a7e18%22&limit=1` | Exact document ID, set ID and v1 | `0b468c60b5e5234922bed39746714534782f8eefac9e786b0fbfd94339c77236` |
| Remedy 3848 NDC | `https://api.fda.gov/drug/ndc.json?search=openfda.spl_set_id:%226600f22e-d303-4fe3-8212-accd6fb06e62%22&limit=100` | Exact product/set/document identity; missing `is_original_packager` is not used | `a28b9e1298f668c7adcf47216b111d1addb69c23ad8b81f3b57807c6b6a45e58` |
| Remedy 3848 label | `https://api.fda.gov/drug/label.json?search=set_id:%226600f22e-d303-4fe3-8212-accd6fb06e62%22&limit=1` | Exact ID/set/v8; `/results/0/openfda/original_packager_product_ndc/0 = 75834-258` | `d41462f0fed7bc0f5f04587ebf275d31ea40593ffa8c4d1a7c6f5f9018832ea4` |
| Remedy 3783 NDC | `https://api.fda.gov/drug/ndc.json?search=openfda.spl_set_id:%228821431a-c387-4b75-9540-f92bd455e961%22&limit=100` | Exact product/set/document identity; missing `is_original_packager` is not used | `ef8e7dce06dcf063ead2f37b46e7b9f4b80be81a331b0630c58690ea317a3733` |
| Remedy 3783 label | `https://api.fda.gov/drug/label.json?search=set_id:%228821431a-c387-4b75-9540-f92bd455e961%22&limit=1` | Exact ID/set/v8; `/results/0/openfda/original_packager_product_ndc/0 = 75834-256` | `63bc29727529a33a30fbb9584983cebcf53bdfc4e135b92d916a43fbc5e6890a` |
| Remedy 4321 NDC | `https://api.fda.gov/drug/ndc.json?search=openfda.spl_set_id:%22604a011e-6c64-4895-8f6e-d28f119c4c22%22&limit=100` | Exact product/set/document identity; missing `is_original_packager` is not used | `f5cc7316ee12155e4160c302785baf0739f76b51bd3fe4e0e261f2e915cd688a` |
| Remedy 4321 label | `https://api.fda.gov/drug/label.json?search=set_id:%22604a011e-6c64-4895-8f6e-d28f119c4c22%22&limit=1` | Exact ID/set/v2; `/results/0/openfda/original_packager_product_ndc/0 = 75834-257` | `45f83d145d5d94a2601cecd6968dd6c4d8ccd3fdcbe80e90a04663e643903b4e` |
| ANDA213853 | `https://api.fda.gov/drug/drugsfda.json?search=application_number:%22ANDA213853%22&limit=1` | `/results/0/{application_number,sponsor_name}` and harmonized IDs: application sponsor is a separate role axis | `9e797be06ee80589d1c3689e4204542455ef2e3c71dec9c179f2b509616bb425` |

Only official FDA, openFDA, NLM, and DailyMed sources were used. No blog, company site,
Wikipedia, nonofficial API/database, or search-result snippet was used as evidence.

## 15. Hash manifest

### Post-research correction artifacts

| Artifact | SHA-256 |
| --- | --- |
| Atorvastatin raw XML, NIVAGEN v17 | `bad95508b99be9b19636428930f0eee4a97cac2e45fb42de4a8bdcb5a570e886` |
| Normalized parser artifact | `18af54d7d53543e7100cda8652468a211e7be9a0eae2dc232459aa7cc0560d53` |
| Technical sample artifact | `107ea29d52523aab0283ec9aab8686d0f4ac989464ba2c6a154dda94b009c0ba` |
| Technical sample manifest | `51d5f8f75ac9e66a3fc30d1982e024932cb3303a2dabb381a790d45edab2b277` |
| Population result | `de0f01385025ca219d7815ff205c4245abd2371a6a7e9ad3b9c949a6f888f3b9` |
| Population result manifest | `a5da2ab37f81fd28d79da346216643d5c927033bdb2e7a155fc6384dbc8fae4a` |
| Frozen Kill gate | `97d894fb7e83ebfcb36bf3c5350a9e5c720bd8be889a3864857e83edbd7a9f98` |
| Kill gate manifest | `7bd4301666c403fe38f205145c150671e36f7d5ad9906c79c90fbc6e830464c5` |
| Claim-provenance audit | `9fc160659b86546a802bad2bb46213b1ac12723f29aabf1c9bcb03fb7edb5bae` |

### Frozen ODD-005 candidate detail evidence

| Candidate | Tier-1 packaging SHA-256 | Tier-2 XML SHA-256 |
| --- | --- | --- |
| NIVAGEN | `bb25b25afa8944a936d1d7c8bad23737a269cc8daa7fb631e2205a8f1a55e805` | `bad95508b99be9b19636428930f0eee4a97cac2e45fb42de4a8bdcb5a570e886` |
| Umedica USA | `49bce0a1c0e3766cff012123e8b5f84211e2156bbbe9e3e3b3e857f789498c9c` | `9302307d6343e9a2b10a886c186d8217f2d963c091b1fd3a633fd18e0a98a8ed` |
| Remedy 3848 | `d11a05ff52a40a29c64f148880b4370f74007804a9b19bbb60f7d108695f7149` | `1a445a39c267c342ed60003cb3925ea756d3c88ccc7163e38da3857dd8a0d786` |
| Remedy 3783 | `ed67c9e2ae77b4f28bbc7e921a3ba1cc7a4ca72c8625f0ed2038e9e6eccf190d` | `9f47d7c3a19ba2e1dd1ca9b862734ab556f65c5609feeb7203cb00868855f399` |
| Remedy 4321 | `abbfb5c42cf2428f405d135094824fe82b8b766df7965e3e132dd9893460523e` | `5ef0465aca2fbec4acbd476f113f2505cfccb5a0ee54b5a633fbea7de7163d57` |

### Additional official API bodies

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `official-api/drugsfda-ANDA213853.json` | 5,798 | `9e797be06ee80589d1c3689e4204542455ef2e3c71dec9c179f2b509616bb425` |
| `official-api/label-5a7594ca.json` | 183,294 | `0b468c60b5e5234922bed39746714534782f8eefac9e786b0fbfd94339c77236` |
| `official-api/label-604a011e.json` | 181,217 | `45f83d145d5d94a2601cecd6968dd6c4d8ccd3fdcbe80e90a04663e643903b4e` |
| `official-api/label-6600f22e.json` | 181,427 | `d41462f0fed7bc0f5f04587ebf275d31ea40593ffa8c4d1a7c6f5f9018832ea4` |
| `official-api/label-7c58bf4a.json` | 189,644 | `3e27d533e96f656a42a567fa011cc836a0c93ccf9efa67cf04f0f3835550530d` |
| `official-api/label-8821431a.json` | 181,562 | `63bc29727529a33a30fbb9584983cebcf53bdfc4e135b92d916a43fbc5e6890a` |
| `official-api/ndc-5a7594ca.json` | 11,103 | `8fd977dcf1d8df87f80a6ad884a2f70636d466489aa77027351b45ffd6958144` |
| `official-api/ndc-604a011e.json` | 2,248 | `f5cc7316ee12155e4160c302785baf0739f76b51bd3fe4e0e261f2e915cd688a` |
| `official-api/ndc-6600f22e.json` | 2,456 | `a28b9e1298f668c7adcf47216b111d1addb69c23ad8b81f3b57807c6b6a45e58` |
| `official-api/ndc-7c58bf4a.json` | 10,887 | `befb5605417a6bfa2e81f0e39eab830dfc3eedf98287a1b6b92178b14ffb5ff7` |
| `official-api/ndc-8821431a.json` | 2,664 | `ef8e7dce06dcf063ead2f37b46e7b9f4b80be81a331b0630c58690ea317a3733` |

Candidate-scoped API total: **11 successful requests and 952,300 response-body bytes**. There
were no official HTTP retries, 429 responses, or non-200 bodies. One earlier sandbox/proxy attempt
failed before reaching the official origin and retained no response body; it is not counted as a
successful official request.

### Official documentation captures

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `official-docs/dailymed-home.html` | 75,305 | `31c5eb88ef2e5ae7faf9e641cb30861c7561948aee30f71fc6725dbe8eb64280` |
| `official-docs/fda-business-operation.html` | 50,768 | `25009c3cfb11c4e17509d8f62e12fbfb3ae53b0410dd5ef39aecaf9947047245` |
| `official-docs/fda-drug-development-definitions.html` | 74,177 | `484d196cfc982234a570e98aca3b9b82206c164a736899ecf81ee25d91e7659b` |
| `official-docs/fda-drugsfda-data-files.html` | 34,681 | `aa8314669606a333436883e3c129cafdfd0a3fb4394581e22c456d567eab5cf6` |
| `official-docs/fda-edrls.html` | 46,614 | `98ad17d4f8c978d18e587255f85a9db2f3c3caa567227bb4a323d49efed384d4` |
| `official-docs/fda-ndc-product-file-definitions.html` | 39,095 | `b05f509ce450f8f9c377447b6653b9d419357af1898fd8d8f3cf11c12efc689d` |
| `official-docs/fda-reporting-amount-guide-202402.pdf` | 491,559 | `2117f60c3d7efaf869c7aa0b1b5dda70c26aeee309ea4c4a13d3678dbbd55364` |
| `official-docs/fda-spl-ig-20231208.pdf` | 1,920,318 | `9845e23cb51ee2e7f493b17ed5729b2bc946040244e6f6da2d78c9491a41f983` |
| `official-docs/openfda-druglabel-reference.pdf` | 109,226 | `7712f67d9b306679ae7be66eca61eefccfa34d2024195db31f35c70b3b4fe692` |
| `official-docs/openfda-drugndc-reference.pdf` | 49,573 | `968d551acc07f7f2987459f5951497e6a3fdee8d1c3bfa36049f0be5fd32f451` |
| `official-docs/openfda-drugsfda-overview.html` | 118,130 | `ee794bb0f5deba3acd8b2bdffe395483804f22957f025ede5b1fc7facdedc948` |
| `official-docs/openfda-harmonization.html` | 117,417 | `d6d2d1e112c5f5dc27726469a00abcac7e8fa7956a0f412b8c8e89dbfdc63e08` |
| `official-docs/openfda-label-overview.html` | 126,680 | `715db2043df249fc5f3d31e3cbb69c777a6de35c540850797154f797ea36ccbd` |
| `official-docs/openfda-ndc-overview.html` | 119,852 | `9087b71a91891fac6b712cb1d63ec0f8626c5f5a3a1b009d90a603ae38128e89` |

Documentation capture total: **14 successful body responses and 3,373,395 stored body bytes**.
Together with the candidate APIs, the ignored evidence directory contains 25 successful exact
body captures totaling **4,325,695 bytes**, plus matching header files. Documentation browsing
through the research interface does not expose an auditable underlying HTTP-request/byte count;
it is therefore not falsely included in those exact-capture totals. It did not access additional
candidate endpoints.

## 16. Reproduction instructions

Reproduction should prefer the retained bytes and must not update the frozen ODD-005 parent.

1. Verify the immutable parent files by hash only; do not open the parent database through
   SQLite:

   ```powershell
   $Parent = 'D:\OpenDrugDatabase\data\live\odd005-canary-20260809'
   Get-FileHash "$Parent\database\odd.sqlite3" -Algorithm SHA256
   Get-FileHash "$Parent\reports\report.json" -Algorithm SHA256
   Get-FileHash "$Parent\evidence\dailymed\enrichment\snapshots\75ab3852-a58e-5eaa-ad55-35fec3a5e06f\manifest.json" -Algorithm SHA256
   ```

2. Recalculate retained research-body hashes:

   ```powershell
   $Research = 'D:\OpenDrugDatabase\data\live\odd006-repackager-research-20260810'
   Get-ChildItem -LiteralPath $Research -Recurse -File |
     Where-Object Extension -in '.json', '.pdf', '.html' |
     Sort-Object FullName |
     Get-FileHash -Algorithm SHA256
   ```

3. Inspect, without a new request, the explicit NDC fact and identity joins:

   ```powershell
   $Api = "$Research\official-api"
   (Get-Content -Raw "$Api\ndc-7c58bf4a.json" | ConvertFrom-Json).results |
     Select-Object product_ndc, spl_id, openfda
   (Get-Content -Raw "$Api\label-7c58bf4a.json" | ConvertFrom-Json).results |
     Select-Object id, set_id, version, effective_time, openfda
   ```

4. If a future investigator intentionally creates a new observation, use exact set-ID queries,
   retain the response and headers, and treat any changed bytes as a new research snapshot. The
   query templates used here were:

   ```text
   https://api.fda.gov/drug/ndc.json?search=openfda.spl_set_id:"<SET_ID>"&limit=100
   https://api.fda.gov/drug/label.json?search=set_id:"<SET_ID>"&limit=1
   https://api.fda.gov/drug/drugsfda.json?search=application_number:"ANDA213853"&limit=1
   ```

5. Parse retained XML only with DTD loading, external entity resolution, and network access
   disabled. Confirm set ID, document ID, and version before examining product-source locators.

6. Audit the separately scoped code and documentation changes with `git diff --check`. Do not
   stage ignored API responses, XML, databases, PDFs, HTML, headers, or runtime reports.

The reproduction commands do not select a candidate, revise a decision, ingest Atorvastatin, or
access the remaining nine ingredients.
