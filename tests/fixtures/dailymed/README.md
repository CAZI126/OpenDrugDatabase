# DailyMed test fixtures

These files are intentionally small, offline inputs for ODD-001 and ODD-002 tests. They are not a
DailyMed corpus mirror, and retaining them here is not a general determination about redistribution
rights for DailyMed collections.

- `apixaban_eliquis_v30.xml` is a deliberately reduced derivative test fixture. Its XML comment
  explicitly states that it is not the complete official ELIQUIS label.
- `apixaban_search.json` is a synthetic mocked search response. It combines the reviewed ELIQUIS
  candidate metadata used by the selection tests with an invented decoy candidate; it must not be
  treated as an exact DailyMed response.
- `history/apixaban_eliquis_v29.xml` and `history/apixaban_eliquis_v30.xml` are exact, genuine source
  bytes retained for the two-version temporal-diff test.
- `history/eliquis_history.json` is the exact DailyMed history response used as ordering evidence.
- `history/fixture_manifest.json` records source URLs, version identities, dates, hashes, purpose,
  and genuine-fixture status for the ODD-002 evidence.

`SHA256SUMS` pins every DailyMed data fixture and the ODD-002 provenance manifest. Tests and
`scripts/verify_fixture_integrity.py` fail if any pinned bytes change.
