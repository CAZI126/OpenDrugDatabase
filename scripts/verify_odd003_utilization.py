"""Independently verify the committed ODD-003 utilization input identity."""

from __future__ import annotations

from odd.provenance.hashing import sha256_bytes
from odd.utilization import canonical_utilization_list_bytes, load_utilization_list

EXPECTED_NAMES = (
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
EXPECTED_CANONICAL_SHA256 = "0b0cee921586ed377c982d396b5d8225fff05905a1417dee05a93bd36dcf7ee1"


def main() -> None:
    first = load_utilization_list("us-top10-2023")
    second = load_utilization_list("us-top10-2023")
    canonical = canonical_utilization_list_bytes(first)
    if canonical != canonical_utilization_list_bytes(second):
        raise SystemExit("ODD-003 utilization canonical serialization changed between reads")
    if tuple(item.ingredient_name for item in first.entries) != EXPECTED_NAMES:
        raise SystemExit("ODD-003 utilization ingredient order does not match the fixed input")
    if any(item.metric_value is not None for item in first.entries):
        raise SystemExit("ODD-003 utilization fixture unexpectedly contains metric counts")
    digest = sha256_bytes(canonical)
    if digest != EXPECTED_CANONICAL_SHA256:
        raise SystemExit(
            "ODD-003 utilization canonical hash changed: "
            f"expected {EXPECTED_CANONICAL_SHA256}, got {digest}"
        )
    print(
        "ODD-003 utilization-list integrity: OK "
        f"({first.utilization_list_id}, sha256={digest})"
    )


if __name__ == "__main__":
    main()
