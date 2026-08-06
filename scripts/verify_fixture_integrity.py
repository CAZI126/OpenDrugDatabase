"""Verify committed offline fixture bytes against their reviewed SHA-256 manifest."""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURE_DIRECTORY = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "dailymed"
MANIFEST = FIXTURE_DIRECTORY / "SHA256SUMS"


def verify() -> list[str]:
    failures: list[str] = []
    for line_number, line in enumerate(MANIFEST.read_text(encoding="ascii").splitlines(), 1):
        if not line.strip():
            continue
        try:
            expected, filename = line.split("  ", 1)
        except ValueError:
            failures.append(f"SHA256SUMS:{line_number}: malformed line")
            continue
        path = FIXTURE_DIRECTORY / filename
        if not path.is_file():
            failures.append(f"missing fixture: {filename}")
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
    fixture_count = sum(1 for line in MANIFEST.read_text(encoding="ascii").splitlines() if line)
    print(f"DailyMed fixture integrity: OK ({fixture_count} files)")


if __name__ == "__main__":
    main()
