"""Verify committed offline fixture bytes against their reviewed SHA-256 manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "dailymed"
MANIFESTS = (
    FIXTURE_DIRECTORY / "SHA256SUMS",
    FIXTURE_DIRECTORY / "odd003" / "SHA256SUMS",
)


def verify() -> list[str]:
    failures: list[str] = []
    for manifest in MANIFESTS:
        base = manifest.parent
        for line_number, line in enumerate(
            manifest.read_text(encoding="ascii").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                expected, filename = line.split("  ", 1)
            except ValueError:
                failures.append(f"{manifest.name}:{line_number}: malformed line")
                continue
            path = base / filename
            if not path.is_file():
                failures.append(f"missing fixture: {path.relative_to(FIXTURE_DIRECTORY)}")
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                failures.append(f"{filename}: expected {expected}, got {actual}")
    return failures


def main() -> None:
    failures = verify()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    fixture_count = sum(
        1
        for manifest in MANIFESTS
        for line in manifest.read_text(encoding="ascii").splitlines()
        if line
    )
    print(f"DailyMed fixture integrity: OK ({fixture_count} files)")


if __name__ == "__main__":
    main()
