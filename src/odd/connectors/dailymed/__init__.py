"""DailyMed metadata lookup, deterministic selection, and SPL download.

``select_apixaban_candidate`` stays reachable as
``odd.connectors.dailymed.select_apixaban_candidate`` but is resolved on first
use. Retrieving and preserving an official document must never require importing
a rule that chooses between candidates.
"""

from typing import TYPE_CHECKING, Any

from odd.connectors.dailymed.client import DailyMedConnector

if TYPE_CHECKING:
    from odd.connectors.dailymed.selection import select_apixaban_candidate

__all__ = ["DailyMedConnector", "select_apixaban_candidate"]


def __getattr__(name: str) -> Any:
    if name == "select_apixaban_candidate":
        from odd.connectors.dailymed import selection

        return selection.select_apixaban_candidate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
