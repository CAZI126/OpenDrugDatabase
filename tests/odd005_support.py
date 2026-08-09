"""Offline synthetic ODD-005 transport and service helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from odd.connectors.dailymed.client import DailyMedConnector, HTTPResponse
from odd.service import ODDService, create_service
from tests.odd003_support import synthetic_spl
from tests.odd004_support import discovery_body, discovery_candidate, response
from tests.odd_support import FixedClock

BASE_URL = "https://dailymed.example/services/v2"


class EnrichmentTransport:
    """Official-shape synthetic search, packaging detail, and SPL responses."""

    def __init__(
        self,
        *,
        combination_rank: int | None = None,
        packaging_failure_rank: int | None = None,
        set_id_drift_rank: int | None = None,
        source_drift_rank: int | None = None,
        packaging_status: int = 200,
        packaging_pages: dict[str, list[list[dict[str, object]]]] | None = None,
        malformed_xml_rank: int | None = None,
        malformed_packaging_rank: int | None = None,
        published_date_drift_rank: int | None = None,
        xml_status: int = 200,
    ) -> None:
        self.combination_rank = combination_rank
        self.packaging_failure_rank = packaging_failure_rank
        self.set_id_drift_rank = set_id_drift_rank
        self.source_drift_rank = source_drift_rank
        self.packaging_status = packaging_status
        self.packaging_pages = packaging_pages or {}
        self.malformed_xml_rank = malformed_xml_rank
        self.malformed_packaging_rank = malformed_packaging_rank
        self.published_date_drift_rank = published_date_drift_rank
        self.xml_status = xml_status
        self.requests: list[str] = []
        self.by_set_id: dict[str, tuple[str, int]] = {}

    @property
    def packaging_request_count(self) -> int:
        return sum("/packaging.json?" in value for value in self.requests)

    @property
    def xml_request_count(self) -> int:
        return sum(value.endswith(".xml") for value in self.requests)

    def get(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        timeout: float,
        max_bytes: int,
    ) -> HTTPResponse:
        del headers, timeout
        self.requests.append(url)
        if "/spls.json?" in url:
            ingredient = parse_qs(urlparse(url).query)["drug_name"][0]
            rank = _rank_for_ingredient(ingredient)
            candidate = discovery_candidate(ingredient, rank=rank)
            set_id = str(candidate["setid"])
            self.by_set_id[set_id] = (ingredient, rank)
            body = discovery_body([candidate])
            return response(body, url=url)
        if "/packaging.json?" in url:
            set_id = unquote(url.split("/spls/", 1)[1].split("/packaging", 1)[0])
            ingredient, rank = self.by_set_id[set_id]
            page = int(parse_qs(urlparse(url).query)["page"][0])
            status = (
                self.packaging_status
                if self.packaging_failure_rank is None
                or rank == self.packaging_failure_rank
                else 200
            )
            if status != 200:
                body = b"synthetic failure"
                return response(
                    body,
                    status=status,
                    content_type="text/plain",
                    url=url,
                )
            if rank == self.malformed_packaging_rank:
                return response(b'{"data":', url=url)
            configured = self.packaging_pages.get(set_id)
            if configured is not None:
                products = configured[page - 1] if page <= len(configured) else []
            else:
                active = [ingredient]
                if rank == self.combination_rank:
                    active.append("synthetic second active")
                products = [
                    {
                        "active_ingredients": [
                            {"name": name, "strength": "1 mg"} for name in active
                        ],
                        "packaging": [],
                        "parts": {},
                        "product_code": f"00000-{rank:03d}",
                        "product_name": ingredient.upper(),
                        "product_name_generic": ingredient,
                    }
                ]
            body = json.dumps(
                {
                    "data": {
                        "products": products,
                        "published_date": (
                            "Aug 09, 2026"
                            if rank == self.published_date_drift_rank
                            else "Aug 08, 2026"
                        ),
                        "setid": (
                            "ffffffff-ffff-4fff-8fff-ffffffffffff"
                            if rank == self.set_id_drift_rank
                            else set_id
                        ),
                        "spl_version": "2" if rank == self.source_drift_rank else "1",
                        "title": f"{ingredient.upper()} synthetic detail",
                    },
                    "metadata": {
                        "current_url": url.split("?", 1)[0],
                        "db_published_date": "Aug 08, 2026",
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
            if len(body) > max_bytes:
                body = body[: max_bytes + 1]
            return response(body, url=url)
        set_id = unquote(url.rsplit("/", 1)[-1].removesuffix(".xml"))
        ingredient, rank = self.by_set_id[set_id]
        if self.xml_status != 200:
            return response(
                b"synthetic XML failure",
                status=self.xml_status,
                content_type="text/plain",
                url=url,
            )
        body = (
            b"<document"
            if rank == self.malformed_xml_rank
            else synthetic_spl(
                ingredient,
                set_id,
                "2" if rank == self.source_drift_rank else "1",
            )
        )
        return response(body, content_type="application/xml", url=url)


def odd005_service(
    tmp_path: Path,
    **transport_options: object,
) -> tuple[ODDService, EnrichmentTransport, str]:
    transport = EnrichmentTransport(**transport_options)
    connector = DailyMedConnector(
        base_url=BASE_URL,
        clock=FixedClock(),
        inter_request_delay_seconds=0,
        transport=transport,
    )
    application = create_service(
        data_root=tmp_path / "data",
        database_path=tmp_path / "odd.sqlite3",
        connector=connector,
        clock=FixedClock(),
    )
    parent, _items = application.batch_plan(
        "us-top10-2023", new_observation=True
    )
    parent_artifact = application.batch_run(run_id=parent.batch_run_id)
    return application, transport, parent_artifact.report.batch_run.batch_run_id


def _rank_for_ingredient(ingredient: str) -> int:
    names = (
        "atorvastatin",
        "metformin",
        "levothyroxine",
        "lisinopril",
        "amlodipine",
        "metoprolol",
        "albuterol",
        "losartan",
        "gabapentin",
        "omeprazole",
    )
    return names.index(ingredient) + 1
