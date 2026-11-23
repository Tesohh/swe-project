"""Collect stage: turn public dataset metadata into manifest CSVs.

For now: MTG-Jamendo. The metadata TSVs are cached in ml/data/jamendo,
the output manifest goes to ml/data/manifests.
"""

import argparse
import csv
import json
import sys
import typing
import urllib.request
from collections import Counter
from pathlib import Path

from ml.dataset.manifest import TAG_SEPARATOR, ManifestRow
from ml.dataset.vocabs import AudioType, LabelOrigin, Source

RAW_BASE = "https://raw.githubusercontent.com/MTG/mtg-jamendo-dataset/master/data"
# Direct per-track mp3 endpoint, verified reachable
AUDIO_URL_TEMPLATE = "https://mp3d.jamendo.com/?trackid={track_id}&format=mp31"

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
CACHE_DIR = DATA_DIR / "jamendo"
MANIFEST_DIR = DATA_DIR / "manifests"
TAG_MAP_PATH = DATA_DIR / "jamendo_tag_map.json"

DEFAULTS = {"duration_min": 60.0, "duration_max": 600.0, "per_genre": 200}


def collect_jamendo(
    out_path: Path,
    per_genre: int = 200,
    duration_min: float = 60.0,
    duration_max: float = 600.0,
) -> None:
    """Build a balanced manifest from the MTG-Jamendo tags."""
    tag_map = _load_tag_map(TAG_MAP_PATH)
    meta = _load_meta(CACHE_DIR / "jamendo_meta.tsv")
    tags_by_track = _load_tags(CACHE_DIR / "jamendo_autotagging.tsv")
    # the mood/theme subset adds mood tags for tracks that the base file lacks
    _merge_tags(tags_by_track, _load_tags(CACHE_DIR / "jamendo_moodtheme.tsv"))

    rows = []
    for track_id, track in tags_by_track.items():
        if track_id not in meta:
            continue
        # tsv ids look like track_0000946, the mp3 endpoint wants the number
        numeric_id = int(track_id.removeprefix("track_"))
        genre, mood = _map_tags(track.tags, tag_map)
        if not genre:
            continue
        info = meta[track_id]
        if not duration_min <= track.duration <= duration_max:
            continue
        rows.append(
            ManifestRow(
                url=AUDIO_URL_TEMPLATE.format(track_id=numeric_id),
                title=info["title"],
                artist=info["artist"],
                source=Source.MTG_JAMENDO,
                genre=genre,
                mood=mood,
                audio_type=AudioType.MUSIC,
                label_origin=LabelOrigin.DATASET_TAG,
                notes=f"jamendo tags: {TAG_SEPARATOR.join(sorted(track.tags))}",
            )
        )

    selected = _balance_by_genre(rows, per_genre)
    selected = _drop_title_duplicates(selected)
    _write_manifest(out_path, selected)
    genre_stats = Counter(tag for row in selected for tag in row.genre)
    mood_stats = Counter(tag for row in selected for tag in row.mood)
    mooded = sum(1 for row in selected if row.mood)
    print(f"wrote {len(selected)} rows to {out_path}")
    print("genre counts:", ", ".join(f"{tag}: {count}" for tag, count in genre_stats.most_common()))
    print(f"mood counts: rows with mood: {mooded}, ", ", ".join(f"{tag}: {count}" for tag, count in mood_stats.most_common()))


def _load_tag_map(path: Path) -> dict[str, dict[str, list[str] | None]]:
    return json.loads(path.read_text())


def _load_meta(path: Path) -> dict[str, dict[str, str]]:
    """track id -> title, artist from raw.meta.tsv."""
    meta: dict[str, dict[str, str]] = {}
    with path.open() as file:
        next(file)  # skip tsv header
        for parts in _tsv_rows(file):
            # raw.meta.tsv columns: track_id, artist_id, album_id, title, artist, album, release, url
            meta[parts[0]] = {"title": parts[3], "artist": parts[4]}
    return meta


class TrackTags(typing.NamedTuple):
    duration: float
    tags: list[str]


def _load_tags(path: Path) -> dict[str, TrackTags]:
    """track id -> duration and raw tags from autotagging.tsv."""
    tags: dict[str, TrackTags] = {}
    with path.open() as file:
        next(file)  # skip tsv header
        for parts in _tsv_rows(file):
            # autotagging.tsv columns: track_id, artist_id, album_id, path, duration, tags
            previous = tags.get(parts[0])
            appended = previous.tags + parts[5].split() if previous else parts[5].split()
            duration = float(parts[4])
            tags[parts[0]] = TrackTags(
                duration=previous.duration if previous else duration,
                tags=appended,
            )
    return tags


def _merge_tags(base: dict[str, TrackTags], extra: dict[str, TrackTags]) -> None:
    """Add tags from the mood/theme subset into the base tags."""
    for track_id, entry in extra.items():
        previous = base.get(track_id)
        merged_tags = previous.tags + entry.tags if previous else entry.tags
        base[track_id] = TrackTags(
            duration=previous.duration if previous else entry.duration,
            tags=merged_tags,
        )


def _tsv_rows(file) -> list[list[str]]:
    return [line.rstrip("\n").split("\t") for line in file]


def _map_tags(
    tags: list[str], tag_map: dict[str, dict[str, list[str] | None]]
) -> tuple[list[str], list[str]]:
    genre: list[str] = []
    mood: list[str] = []
    for raw_tag in tags:
        category, _, tag = raw_tag.partition("---")
        key = "mood" if category == "mood/theme" else category
        if key not in ("genre", "mood"):
            continue
        mapped = tag_map.get(key, {}).get(tag.lower())
        if not mapped:
            continue
        out = genre if key == "genre" else mood
        for target in mapped:
            if target not in out:
                out.append(target)
    return genre, mood


def _drop_title_duplicates(rows: list[ManifestRow]) -> list[ManifestRow]:
    """Keep one copy of same title+artist rows, most are re-uploads."""
    seen: set[tuple[str, str]] = set()
    kept = []
    for row in rows:
        key = (row.title.lower(), row.artist.lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(row)
    return kept


def _balance_by_genre(rows: list[ManifestRow], per_genre: int) -> list[ManifestRow]:
    """Dedupe tracks and spread them evenly over genres: a track with three
    genre tags counts toward all three, so rarer genres fill up first."""
    by_genre: dict[str, list[ManifestRow]] = {}
    for row in rows:
        for tag in row.genre:
            by_genre.setdefault(tag, []).append(row)
    selected_ids: set[str] = set()
    selected: list[ManifestRow] = []
    remaining = dict.fromkeys(by_genre, per_genre)
    # round-robin over genres so rare genres keep their share
    for genre in sorted(by_genre):
        for row in by_genre[genre]:
            if remaining[genre] <= 0:
                break
            if row.id in selected_ids:
                continue
            selected_ids.add(row.id)
            selected.append(row)
            for tag in row.genre:
                if tag in remaining:
                    remaining[tag] -= 1
    return selected


def _write_manifest(out_path: Path, rows: list[ManifestRow]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [name for name in ManifestRow.model_fields if name != "id"]
    with out_path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["id", *fields])
        writer.writeheader()
        for row in rows:
            # ids are re-generated at collect time, so re-runs stay stable
            record = row.model_dump(mode="json") | {"id": ""}
            record["genre"] = TAG_SEPARATOR.join(row.genre)
            record["mood"] = TAG_SEPARATOR.join(row.mood)
            writer.writerow(record)


def _ensure_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files = {
        "jamendo_autotagging.tsv": f"{RAW_BASE}/autotagging.tsv",
        "jamendo_moodtheme.tsv": f"{RAW_BASE}/autotagging_moodtheme.tsv",
        "jamendo_meta.tsv": f"{RAW_BASE}/raw.meta.tsv",
    }
    for name, url in files.items():
        target = CACHE_DIR / name
        if target.exists() and target.stat().st_size > 0:
            continue
        print(f"downloading {url} -> {target}")
        urllib.request.urlretrieve(url, target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a collect-stage manifest from MTG-Jamendo")
    parser.add_argument("--out", type=Path, default=MANIFEST_DIR / "jamendo.csv")
    parser.add_argument("--per-genre", type=int, default=DEFAULTS["per_genre"])
    parser.add_argument("--duration-min", type=float, default=DEFAULTS["duration_min"])
    parser.add_argument("--duration-max", type=float, default=DEFAULTS["duration_max"])
    args = parser.parse_args(argv)

    _ensure_cache()
    collect_jamendo(
        out_path=args.out,
        per_genre=args.per_genre,
        duration_min=args.duration_min,
        duration_max=args.duration_max,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
