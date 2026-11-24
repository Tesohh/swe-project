"""One-off rescue: rename downloaded mp3s (old random ids) to the new stable ids.

Matches by the ID3 title/artist tags every jamendo download carries, so the
existing audio does not need a fresh multi-hour download.
Run:  uv run python -m ml.dataset.rescue data/raw data/manifests/jamendo.csv
Then re-run the downloader to fetch the few files it could not match.
"""

import argparse
import json
from difflib import get_close_matches
from pathlib import Path

from mutagen import File as AudioFile


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rename downloaded mp3s to stable manifest ids via ID3 tags"
    )
    parser.add_argument("audio_dir", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument(
        "--specs-dir",
        type=Path,
        default=None,
        help="also rename preprocessed .npy files and rewrite the sidecar ids",
    )
    args = parser.parse_args(argv)

    rows = _index_manifest_rows(args.manifest)
    mapping: dict[str, str] = {}
    renamed, already_ok, unmatched, no_tags = 0, 0, [], 0
    for path in sorted(args.audio_dir.glob("*.mp3")):
        match = _match_by_tags(path, rows)
        if match is None:
            no_tags += 1
            unmatched.append(path.stem)
            continue
        if path.stem == match:
            already_ok += 1
            continue
        mapping[path.stem] = match
        target = args.audio_dir / f"{match}.mp3"
        if target.exists():
            # two files matched the same row: keep the first, drop the copy later
            print(f"collides with existing {target.name}, leaving {path.name} in place")
            continue
        path.rename(target)
        renamed += 1
    if args.specs_dir:
        renamed_specs = _rename_specs(args.specs_dir, mapping)
        print(f"renamed {renamed_specs} spectrograms")
    _write_mapping(args.audio_dir, mapping)
    print(f"renamed {renamed}, already correct {already_ok}, no tag match {no_tags}")
    for stem in unmatched[:20]:
        print(f"  unmatched: {stem}")
    return 0


def _write_mapping(audio_dir: Path, mapping: dict[str, str]) -> None:
    """Record old -> new ids, so the specs rescue needs no re-matching."""
    with (audio_dir / "rescued_ids.jsonl").open("w") as file:
        for old, new in mapping.items():
            file.write(json.dumps({"old": old, "new": new}) + "\n")


def _rename_specs(specs_dir: Path, mapping: dict[str, str]) -> int:
    """Rename .npy files by the same old->new mapping and fix sidecar ids."""
    renamed = 0
    for old, new in mapping.items():
        source = specs_dir / f"{old}.npy"
        target = specs_dir / f"{new}.npy"
        if source.exists() and not target.exists():
            source.rename(target)
            renamed += 1
    sidecar = specs_dir / "preprocessed.jsonl"
    if sidecar.exists():
        lines = []
        for line in sidecar.read_text().splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            record["id"] = mapping.get(record["id"], record["id"])
            lines.append(json.dumps(record))
        sidecar.write_text("\n".join(lines) + "\n")
    return renamed


def _index_manifest_rows(manifest_path: Path) -> "_TagIndex":
    import csv

    index: dict[str, str] = {}
    titles: dict[str, list[str]] = {}
    for row in csv.DictReader(manifest_path.open()):
        key = f"{_normalize(row['title'])}|{_normalize(row['artist'])}"
        index[key] = row["id"]
        titles.setdefault(_normalize(row["title"]), []).append(key)
    return _TagIndex(index, titles)


class _TagIndex:
    def __init__(self, index: dict[str, str], titles: dict[str, list[str]]):
        self.index = index
        self.titles = titles

    def lookup(self, title: str, artist: str) -> str | None:
        key = f"{_normalize(title)}|{_normalize(artist)}"
        if key in self.index:
            return self.index[key]
        # tag typos or extra (live)markings: fall back to a title-only close match
        close = get_close_matches(_normalize(title), self.titles.keys(), n=1, cutoff=0.9)
        if close:
            candidates = [k for k in self.titles[close[0]] if _normalize(artist) in k]
            if len(candidates) == 1:
                return self.index[candidates[0]]
        return None


def _match_by_tags(path: Path, rows: _TagIndex) -> str | None:
    audio = AudioFile(str(path), easy=True)
    if audio is None or audio.tags is None:
        return None
    title = (audio.tags.get("title") or [""])[0]
    artist = (audio.tags.get("artist") or [""])[0]
    if not title or not artist:
        return None
    return rows.lookup(title, artist)


if __name__ == "__main__":
    raise SystemExit(main())
