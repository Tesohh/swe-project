"""dataset-check: validate one or more manifest CSVs and print a report."""

import argparse
import sys
from collections import Counter
from pathlib import Path

from ml.dataset.manifest import load_manifest
from ml.dataset.validate import ManifestReport, check_manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate collect-stage manifest CSVs")
    parser.add_argument("paths", nargs="+", type=Path, help="manifest CSV files")
    parser.add_argument(
        "--stats-only", action="store_true", help="skip cross checks, print counts only"
    )
    args = parser.parse_args(argv)

    exit_code = 0
    for path in args.paths:
        if not path.exists():
            print(f"error: {path}: file not found")
            exit_code = 2
            continue
        report = check_manifest(load_manifest(path))
        _print_report(path, report, stats_only=args.stats_only)
        if not report.is_valid:
            exit_code = 1
    return exit_code


def _print_report(path: Path, report: ManifestReport, stats_only: bool) -> None:
    print(f"== {path}")
    manifest = report.manifest
    print(f"rows: {len(manifest.rows)} valid, {len(manifest.errors)} broken")

    for error in manifest.errors:
        print(f"  row {error.line}: {error.title or error.url}: {error.error}")
    if not stats_only:
        for error in report.cross_errors:
            row = f" (row id {error.row_id})" if error.row_id else ""
            print(f"  {error.kind}{row}: {error.detail}")

    print("genre counts:", _format_counts(report.genre_counts))
    print("mood counts: ", _format_counts(report.mood_counts))
    print("sources:     ", _format_counts(report.source_counts))
    print("audio types: ", _format_counts(report.audio_type_counts))
    if not report.is_valid:
        print("result: INVALID")
    else:
        print("result: OK")
    print()


def _format_counts(counter: Counter[str]) -> str:
    return ", ".join(f"{name}: {count}" for name, count in counter.most_common()) or "none"


if __name__ == "__main__":
    sys.exit(main())
