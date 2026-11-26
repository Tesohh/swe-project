"""Assemble stage: collected manifests -> one training samples jsonl.

Reads every manifest CSV, keeps the fields the trainer needs, and writes
one jsonl row per sample. Resume-safe: rows already in the output are
skipped, so re-runs only append new samples. Rows with no id are dropped,
and parent genres are filled in (techno/house also carry electronic).
"""

import argparse
import csv
import json
from pathlib import Path

from ml.dataset.clean_seeds import IMPLIED_GENRES


def with_parents(genres: list[str]) -> list[str]:
    out = list(genres)
    for child, parents in IMPLIED_GENRES.items():
        if child in out:
            out += [p for p in parents if p not in out]
    return out


def assemble(manifests: list[Path], out_path: Path) -> int:
    done = set()
    if out_path.exists():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["id"])
    written = 0
    with out_path.open("a") as out:
        for manifest in manifests:
            for row in csv.DictReader(manifest.open()):
                if not row["id"] or row["id"] in done:
                    continue
                sample = {
                    "id": row["id"],
                    "artist": row.get("artist") or "",
                    "title": row.get("title") or "",
                    "genre": with_parents([t for t in (row.get("genre") or "").split("|") if t]),
                    "mood": [t for t in (row.get("mood") or "").split("|") if t],
                    "audio_type": row.get("audio_type") or "music",
                    "origin": row.get("label_origin") or "",
                }
                out.write(json.dumps(sample) + "\n")
                done.add(row["id"])
                written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assemble manifests into the training samples jsonl"
    )
    parser.add_argument("manifests", nargs="+", type=Path, help="manifest CSV files")
    parser.add_argument("--out", type=Path, required=True, help="output jsonl")
    args = parser.parse_args(argv)
    written = assemble(args.manifests, args.out)
    print(f"assemble wrote {written} samples to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
