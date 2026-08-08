# ODD-003 mocked DailyMed metadata

`top10_candidates.json` is synthetic metadata created solely to exercise deterministic
ODD-003 discovery, rejection, ambiguity, and batch behavior without live network access.
It is not a DailyMed export and does not establish current product availability or clinical
equivalence. Its SHA-256 is pinned in `SHA256SUMS`.

The mocked source downloads used by tests are explicitly generated synthetic mutations of
the already pinned Eliquis v30 fixture. They are never inserted into production lineage or
described as genuine labels.

`highly_unmapped_spl.xml` is a tiny `synthetic_test_fixture` with five unknown sections. It proves
that a structurally parseable document can be reported as highly unmapped without inventing
semantic content. It is not inserted into a production source lineage.
