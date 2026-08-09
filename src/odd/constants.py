"""Versioned constants that participate in deterministic normalized identity."""

from uuid import UUID

PARSER_VERSION = "spl-parser/1.0.0"
SCHEMA_VERSION = "odd-normalized/1.0.0"
MAPPING_VERSION = "spl-section-mapping/1.0.0"
RAW_MANIFEST_VERSION = "odd-raw-manifest/2.0.0"
SELECTION_RULE_VERSION = "dailymed-apixaban-selection/1.0.0"
HISTORICAL_SELECTION_RULE_VERSION = "dailymed-explicit-history-version/1.0.0"
DIFF_ENGINE_VERSION = "section-diff/1.0.0"
CONNECTOR_VERSION = "dailymed-connector/4.0.0"
BATCH_SELECTION_RULE_VERSION = "dailymed-top10-validation-selection/2.0.0"
BATCH_REPORT_VERSION = "odd-batch-report/2.0.0"
LIVE_SNAPSHOT_VERSION = "dailymed-live-snapshot/1.0.0"
LIVE_OBSERVATION_MODE = "LIVE"
UTILIZATION_LIST_SCHEMA_VERSION = "odd-utilization-list/1.0.0"
SELECTION_SCOPE = "one deterministic validation label for this active ingredient"
CONTENT_ASSISTED_MATCH_THRESHOLD = 0.92

# This namespace is an ODD internal implementation constant. UUIDs derived from it
# are internal identifiers and must never be presented as regulatory identifiers.
ODD_UUID_NAMESPACE = UUID("3f1738a8-5157-5e38-b4af-a356faf0638e")

INITIAL_CONCEPTS = (
    "boxed_warning",
    "indications_and_usage",
    "dosage_and_administration",
    "dosage_forms_and_strengths",
    "contraindications",
    "warnings_and_precautions",
    "adverse_reactions",
    "drug_interactions",
    "use_in_specific_populations",
    "pregnancy",
    "lactation",
    "pediatric_use",
    "geriatric_use",
    "renal_impairment",
    "hepatic_impairment",
    "overdosage",
    "clinical_pharmacology",
    "clinical_studies",
    "how_supplied",
    "storage_and_handling",
)
