"""Offline synthetic transport and helpers for ODD-003 tests."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from odd.connectors.dailymed.client import DailyMedConnector, HTTPResponse
from odd.errors import NetworkFailure
from odd.service import ODDService, create_service
from tests.odd_support import ELIQUIS_XML, SET_ID, FixedClock

FIXTURE = Path(__file__).parent / "fixtures" / "dailymed" / "odd003" / "top10_candidates.json"


class Top10Transport:
    def __init__(
        self,
        *,
        reverse_results: bool = False,
        fetch_failure_ingredient: str | None = None,
        parser_failure_ingredient: str | None = None,
        unsupported_ingredient: str | None = None,
        resolve_omeprazole: bool = False,
    ) -> None:
        fixture = json.loads(FIXTURE.read_bytes())
        self.queries: dict[str, list[dict[str, object]]] = fixture["queries"]
        if resolve_omeprazole:
            self.queries["omeprazole"][1]["spl_version"] = "19"
        self.reverse_results = reverse_results
        self.fetch_failure_ingredient = fetch_failure_ingredient
        self.parser_failure_ingredient = parser_failure_ingredient
        self.unsupported_ingredient = unsupported_ingredient
        self.requests: list[str] = []
        self.by_set_id = {
            str(candidate["setid"]): (ingredient, candidate)
            for ingredient, candidates in self.queries.items()
            for candidate in candidates
        }

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
    ) -> HTTPResponse:
        del headers, timeout
        self.requests.append(url)
        if "/spls.json?" in url:
            query = parse_qs(urlparse(url).query).get("drug_name", [""])[0]
            values = list(self.queries.get(query, []))
            if self.reverse_results:
                values.reverse()
            body = json.dumps(
                {"metadata": {"total_elements": str(len(values))}, "data": values},
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            return HTTPResponse(200, url, body, {"content-type": "application/json"})
        set_id = unquote(url.rsplit("/", 1)[-1].removesuffix(".xml"))
        ingredient, candidate = self.by_set_id[set_id]
        if ingredient == self.fetch_failure_ingredient:
            raise NetworkFailure("synthetic fetch failure")
        if ingredient == self.parser_failure_ingredient:
            body = b"<broken>"
        else:
            body = synthetic_spl(
                ingredient,
                set_id,
                str(candidate["spl_version"]),
            )
            if ingredient == self.unsupported_ingredient:
                body = body.replace(b"<document", b"<unsupportedDocument", 1)
                body = body.replace(b"</document>", b"</unsupportedDocument>", 1)
        return HTTPResponse(200, url, body, {"content-type": "application/xml"})


def synthetic_spl(ingredient: str, set_id: str, source_version: str) -> bytes:
    """Create an explicitly synthetic structural fixture; never genuine source lineage."""

    value = ELIQUIS_XML.read_bytes()
    value = value.replace(SET_ID.encode("ascii"), set_id.encode("ascii"))
    value = value.replace(
        b'<versionNumber value="30"/>',
        f'<versionNumber value="{source_version}"/>'.encode("ascii"),
        1,
    )
    value = value.replace(b"apixaban", ingredient.encode("ascii"))
    value = value.replace(b"APIXABAN", ingredient.upper().encode("ascii"))
    value = value.replace(b"ELIQUIS", ingredient.upper().encode("ascii"))
    return value


def odd003_service(
    tmp_path: Path,
    *,
    reverse_results: bool = False,
    fetch_failure_ingredient: str | None = None,
    parser_failure_ingredient: str | None = None,
    unsupported_ingredient: str | None = None,
    resolve_omeprazole: bool = False,
) -> tuple[ODDService, Top10Transport]:
    transport = Top10Transport(
        reverse_results=reverse_results,
        fetch_failure_ingredient=fetch_failure_ingredient,
        parser_failure_ingredient=parser_failure_ingredient,
        unsupported_ingredient=unsupported_ingredient,
        resolve_omeprazole=resolve_omeprazole,
    )
    connector = DailyMedConnector(
        base_url="https://dailymed.example/services/v2",
        transport=transport,
        clock=FixedClock(),
    )
    return (
        create_service(
            data_root=tmp_path / "data",
            database_path=tmp_path / "odd.sqlite3",
            connector=connector,
            clock=FixedClock(),
        ),
        transport,
    )
