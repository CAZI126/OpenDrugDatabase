"""ODD core: the minimal one-way path from an official primary source to AI.

The core does exactly seven things and nothing else:

1. retrieve an official primary source,
2. preserve its bytes unmodified,
3. record the SHA-256 of those bytes,
4. record the version, official identifier, official URL, and retrieval time,
5. extract sections from the preserved bytes,
6. return structured data an AI can consume, carrying provenance and an
   evidence locator for every extracted passage,
7. re-verify that structured data back against the preserved bytes.

The core deliberately does **not** decide which drug is correct, rank
manufacturers or products, adjudicate medical claims, guess missing facts, or
narrow ambiguous candidates. When it cannot know something it reports the
candidates it saw, or ``UNKNOWN``.

Candidate selection, adjudication, and the ODD-006/007/007R research rules are
retained in the repository but are not reachable from this path.
"""

from odd.core.evidence import (
    CORE_EVIDENCE_SCHEMA_VERSION,
    UNKNOWN,
    build_evidence_payload,
)
from odd.core.locator import resolve_locator
from odd.core.pipeline import (
    AcquisitionResult,
    CorePipeline,
    EvidenceResult,
    VerificationReport,
)

__all__ = [
    "AcquisitionResult",
    "CORE_EVIDENCE_SCHEMA_VERSION",
    "CorePipeline",
    "EvidenceResult",
    "UNKNOWN",
    "VerificationReport",
    "build_evidence_payload",
    "resolve_locator",
]
