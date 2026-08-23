"""Serialize a DailyMed candidate exactly as the official response described it.

This is a rendering of observed facts. It applies no rule, keeps no preference,
and is deliberately kept apart from ``selection``, so preserving a candidate
never requires importing anything that could choose between candidates.
"""

from __future__ import annotations

from typing import Any

from odd.models import DailyMedCandidate

__all__ = ["candidate_payload"]


def candidate_payload(candidate: DailyMedCandidate) -> dict[str, Any]:
    return {
        "metadata": candidate.metadata,
        "published_date": candidate.published_date,
        "set_id": candidate.set_id,
        "source_version": candidate.source_version,
        "title": candidate.title,
    }
